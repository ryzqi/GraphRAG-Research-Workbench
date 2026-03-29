"""普通代理服务。

使用 LangChain create_agent + LangGraph checkpointer，实现中间件与 Human-in-the-loop。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.types import Command, Interrupt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.agents.general_chat_agent import (
    SUMMARY_KEEP,
    SUMMARY_TRIGGER,
    build_general_chat_agent,
    build_hitl_interrupt_on,
    build_pending_tool_calls,
)
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.system_time import build_system_time_tool
from app.agents.tools.web_search import has_web_extract_provider, has_web_search_provider
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.settings import get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_adapters import open_mcp_tool_runtime
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.integrations.redis_client import RedisClient
from app.prompts import get_prompt_loader
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_request_dedup import ChatRequestDedup
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence, EvidenceSourceKind
from app.models.model_config import ModelProvider
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatPendingToolApprovalResponse,
    ChatMessageRead,
    EvidenceItem,
    PendingInterruptApproval,
    PendingToolCall,
    ToolApprovalRequest,
)
from app.search.web.citations import (
    append_compact_citations_to_answer,
    extract_external_evidence_from_messages,
)
from app.services.context_builder import ContextBuilder
from app.services.chat_replay_policy import (
    ReplayDecision,
    ReplayMode,
    decide_replay_mode,
)
from app.services.message_normalizer import (
    checkpoint_messages_require_reset,
    extract_response_id,
    extract_text_content,
)
from app.services.streaming import (
    StreamState,
    apply_updates_chunk,
    extract_answer_text,
    extract_message_text,
    extract_stream_delta,
)
from app.utils.token_counter import count_tokens_approximately

logger = logging.getLogger(__name__)

SUMMARY_META_FLAG = "summary"
DEDUP_ATTACH_TIMEOUT_SECONDS = 5.0
DEDUP_RUN_WAIT_TIMEOUT_SECONDS = 25.0
DEDUP_POLL_INTERVAL_SECONDS = 0.5
DEDUP_TABLE_NAME = "chat_request_dedup"
_EXTERNAL_EVIDENCE_META_KEY = "_external_evidence_meta"


def _extract_interrupt_message(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message
    action_requests = payload.get("action_requests")
    if isinstance(action_requests, list):
        for item in action_requests:
            if not isinstance(item, dict):
                continue
            desc = item.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc
    return None


def _extract_interrupt_payload(interrupt: object) -> dict[str, Any] | None:
    if isinstance(interrupt, Interrupt):
        return interrupt.value if isinstance(interrupt.value, dict) else None
    if isinstance(interrupt, dict):
        value = interrupt.get("value")
        if isinstance(value, dict):
            return value
        if "action_requests" in interrupt:
            return interrupt
        return None
    value = getattr(interrupt, "value", None)
    return value if isinstance(value, dict) else None


def _extract_interrupt_id(interrupt: object) -> str | None:
    if isinstance(interrupt, Interrupt):
        if isinstance(interrupt.id, str) and interrupt.id.strip():
            return interrupt.id
        if isinstance(interrupt.value, dict):
            nested_id = interrupt.value.get("id")
            if isinstance(nested_id, str) and nested_id.strip():
                return nested_id
        return None
    if isinstance(interrupt, dict):
        interrupt_id = interrupt.get("id")
        if isinstance(interrupt_id, str) and interrupt_id.strip():
            return interrupt_id
        value = interrupt.get("value")
        if isinstance(value, dict):
            nested_id = value.get("id")
            if isinstance(nested_id, str) and nested_id.strip():
                return nested_id
        return None
    interrupt_id = getattr(interrupt, "id", None)
    if isinstance(interrupt_id, str) and interrupt_id.strip():
        return interrupt_id
    payload = getattr(interrupt, "value", None)
    if isinstance(payload, dict):
        nested_id = payload.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            return nested_id
    return None


def _flatten_interrupts(interrupts: list[object]) -> list[object]:
    flat: list[object] = []
    for interrupt in interrupts:
        if isinstance(interrupt, list):
            flat.extend(interrupt)
            continue
        flat.append(interrupt)
    return flat


def _build_interrupt_entries(interrupts: list[object]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, interrupt in enumerate(_flatten_interrupts(interrupts)):
        payload = _extract_interrupt_payload(interrupt)
        if not isinstance(payload, dict):
            continue
        raw_requests = payload.get("action_requests")
        action_requests: list[dict[str, Any]] = []
        if isinstance(raw_requests, list):
            action_requests = [
                item for item in raw_requests if isinstance(item, dict)
            ]
        interrupt_id = _extract_interrupt_id(interrupt) or f"interrupt_{index + 1}"
        entries.append(
            {
                "interrupt_id": interrupt_id,
                "message": _extract_interrupt_message(payload),
                "action_requests": action_requests,
            }
        )
    return entries


def _extract_action_requests(interrupts: list[object]) -> list[dict[str, Any]]:
    action_requests: list[dict[str, Any]] = []
    for entry in _build_interrupt_entries(interrupts):
        action_requests.extend(entry["action_requests"])
    return action_requests


def _extract_pending_interrupts(pending_writes: object) -> list[object]:
    if not isinstance(pending_writes, list):
        return []
    interrupts: list[object] = []
    for item in pending_writes:
        channel = None
        value = None
        if isinstance(item, tuple):
            if len(item) > 1:
                channel = item[1]
            if len(item) > 2:
                value = item[2]
        else:
            channel = getattr(item, "channel", None)
            value = getattr(item, "value", None)
        if channel != "__interrupt__" or value is None:
            continue
        if isinstance(value, list):
            interrupts.extend(value)
            continue
        interrupts.append(value)
    return interrupts


class GeneralChatService:
    """普通代理服务，支持 MCP 扩展调用和检查点持久化。"""

    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
        *,
        redis: RedisClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._settings = get_settings()
        self._context_builder = ContextBuilder(self._settings)
        self._prompts = get_prompt_loader()
        self._redis = redis
        self._http_client = http_client
        self._dedup_missing_table_warned = False
        self._active_tool_runtime_cm: Any | None = None

    @staticmethod
    def _normalize_client_request_id(client_request_id: str | None) -> str | None:
        if client_request_id is None:
            return None
        normalized = client_request_id.strip()
        return normalized or None

    @staticmethod
    def _is_missing_dedup_table_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        if DEDUP_TABLE_NAME not in message:
            return False
        return (
            "undefinedtableerror" in message
            or f'relation "{DEDUP_TABLE_NAME}" does not exist' in message
            or f"relation '{DEDUP_TABLE_NAME}' does not exist" in message
            or f"no such table: {DEDUP_TABLE_NAME}" in message
        )

    async def _handle_missing_dedup_table_error(self, exc: BaseException) -> bool:
        if not self._is_missing_dedup_table_error(exc):
            return False

        await self._db.rollback()
        if not self._dedup_missing_table_warned:
            logger.warning(
                "chat_request_dedup table missing, dedup disabled for this process; run alembic upgrade head to enable idempotency"
            )
            self._dedup_missing_table_warned = True
        return True

    async def _load_tool_registry_for_session(
        self, *, session: ChatSession
    ) -> tuple[list[Any], dict[str, Any]]:
        include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
        include_web_search = has_web_search_provider(self._settings)
        include_web_extract = has_web_extract_provider(self._settings)
        extensions: list[ToolExtension] = []
        if include_mcp:
            stmt = select(ToolExtension).where(
                ToolExtension.status == ExtensionStatus.ENABLED
            )
            result = await self._db.execute(stmt)
            extensions = list(result.scalars().all())
        return await build_tool_registry(
            settings=self._settings,
            extensions=extensions,
            extra_tools=[build_system_time_tool()],
            include_web_search=include_web_search,
            include_web_extract=include_web_extract,
            include_web_research=False,
            include_web_crawl=False,
            include_mcp=include_mcp,
            redis=self._redis,
            http_client=self._http_client,
        )

    @asynccontextmanager
    async def _load_runtime_tool_registry_for_session(
        self, *, session: ChatSession
    ):
        include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
        include_web_search = has_web_search_provider(self._settings)
        include_web_extract = has_web_extract_provider(self._settings)
        extensions: list[ToolExtension] = []
        if include_mcp:
            stmt = select(ToolExtension).where(
                ToolExtension.status == ExtensionStatus.ENABLED
            )
            result = await self._db.execute(stmt)
            extensions = list(result.scalars().all())

        if not include_mcp:
            yield await build_tool_registry(
                settings=self._settings,
                extensions=[],
                extra_tools=[build_system_time_tool()],
                include_web_search=include_web_search,
                include_web_extract=include_web_extract,
                include_web_research=False,
                include_web_crawl=False,
                include_mcp=False,
                redis=self._redis,
                http_client=self._http_client,
            )
            return

        async with open_mcp_tool_runtime(
            settings=self._settings,
            extensions=extensions,
            allow_external=True,
        ) as (mcp_entries, _diagnostics):
            yield await build_tool_registry(
                settings=self._settings,
                extensions=extensions,
                mcp_entries=mcp_entries,
                extra_tools=[build_system_time_tool()],
                include_web_search=include_web_search,
                include_web_extract=include_web_extract,
                include_web_research=False,
                include_web_crawl=False,
                include_mcp=True,
                redis=self._redis,
                http_client=self._http_client,
            )

    async def _open_runtime_tool_registry_for_session(
        self, *, session: ChatSession
    ) -> tuple[list[Any], dict[str, Any]]:
        await self._close_runtime_tool_registry()
        runtime_cm = self._load_runtime_tool_registry_for_session(session=session)
        tools, tool_meta_by_name = await runtime_cm.__aenter__()
        self._active_tool_runtime_cm = runtime_cm
        return tools, tool_meta_by_name

    async def _close_runtime_tool_registry(self) -> None:
        runtime_cm = getattr(self, "_active_tool_runtime_cm", None)
        if runtime_cm is None:
            return
        self._active_tool_runtime_cm = None
        await runtime_cm.__aexit__(None, None, None)

    async def _claim_request_dedup(
        self,
        *,
        session_id: uuid.UUID,
        client_request_id: str,
    ) -> tuple[ChatRequestDedup | None, bool]:
        stmt = (
            select(ChatRequestDedup)
            .where(
                ChatRequestDedup.session_id == session_id,
                ChatRequestDedup.client_request_id == client_request_id,
            )
            .limit(1)
        )
        try:
            existing = (await self._db.execute(stmt)).scalars().first()
        except ProgrammingError as exc:
            if await self._handle_missing_dedup_table_error(exc):
                return None, True
            raise
        if existing is not None:
            return existing, False

        dedup = ChatRequestDedup(
            session_id=session_id,
            client_request_id=client_request_id,
        )
        self._db.add(dedup)
        try:
            await self._db.commit()
            await self._db.refresh(dedup)
            return dedup, True
        except IntegrityError:
            await self._db.rollback()
            try:
                existing = (await self._db.execute(stmt)).scalars().first()
            except ProgrammingError as exc:
                if await self._handle_missing_dedup_table_error(exc):
                    return None, True
                raise
            if existing is None:  # pragma: no cover - defensive
                raise
            return existing, False
        except ProgrammingError as exc:
            if await self._handle_missing_dedup_table_error(exc):
                return None, True
            raise

    async def _wait_for_dedup_binding(
        self, *, dedup: ChatRequestDedup
    ) -> ChatRequestDedup | None:
        deadline = (
            datetime.now(timezone.utc).timestamp() + DEDUP_ATTACH_TIMEOUT_SECONDS
        )
        while datetime.now(timezone.utc).timestamp() < deadline:
            refreshed_stmt = (
                select(ChatRequestDedup)
                .where(ChatRequestDedup.id == dedup.id)
                .execution_options(populate_existing=True)
            )
            refreshed = (await self._db.execute(refreshed_stmt)).scalars().first()
            if refreshed is None:
                return None
            if refreshed.run_id is not None:
                return refreshed
            await asyncio.sleep(DEDUP_POLL_INTERVAL_SECONDS)
        final_stmt = (
            select(ChatRequestDedup)
            .where(ChatRequestDedup.id == dedup.id)
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(final_stmt)).scalars().first()

    async def _delete_unbound_request_dedup(self, *, dedup: ChatRequestDedup) -> None:
        current = await self._db.get(ChatRequestDedup, dedup.id)
        if current is None or current.run_id is not None:
            return
        await self._db.delete(current)
        await self._db.commit()

    async def _persist_failed_run(self, *, run: AgentRun, error: Exception) -> None:
        try:
            run_id = getattr(run, "id", None)
        except Exception:
            run_id = None
        run.status = AgentRunStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = str(error)
        try:
            await self._db.commit()
        except StaleDataError:
            await self._db.rollback()
            logger.warning(
                "Skip failed run persistence because agent run row no longer exists",
                extra={
                    "run_id": str(run_id or ""),
                    "original_exc_type": type(error).__name__,
                },
            )

    async def _wait_for_run_terminal(
        self,
        *,
        run_id: uuid.UUID,
        timeout_seconds: float = DEDUP_RUN_WAIT_TIMEOUT_SECONDS,
    ) -> AgentRun | None:
        deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
        while datetime.now(timezone.utc).timestamp() < deadline:
            run_stmt = (
                select(AgentRun)
                .where(AgentRun.id == run_id)
                .execution_options(populate_existing=True)
            )
            run = (await self._db.execute(run_stmt)).scalars().first()
            if run is None:
                return None
            if run.status in {
                AgentRunStatus.SUCCEEDED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELED,
            }:
                return run
            await asyncio.sleep(DEDUP_POLL_INTERVAL_SECONDS)
        final_stmt = (
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        return (await self._db.execute(final_stmt)).scalars().first()

    async def _get_latest_assistant_message(
        self, *, session_id: uuid.UUID
    ) -> ChatMessage | None:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.role == MessageRole.ASSISTANT)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        return (await self._db.execute(stmt)).scalars().first()

    async def _get_assistant_message_for_user_message(
        self,
        *,
        session_id: uuid.UUID,
        user_message_id: uuid.UUID | None,
    ) -> ChatMessage | None:
        if user_message_id is None:
            return await self._get_latest_assistant_message(session_id=session_id)
        user_msg = await self._db.get(ChatMessage, user_message_id)
        if user_msg is None:
            return await self._get_latest_assistant_message(session_id=session_id)

        next_user_stmt = (
            select(ChatMessage.created_at)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.role == MessageRole.USER)
            .where(ChatMessage.created_at > user_msg.created_at)
            .order_by(ChatMessage.created_at.asc())
            .limit(1)
        )
        next_user_created_at = (await self._db.execute(next_user_stmt)).scalar_one_or_none()

        assistant_stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.role == MessageRole.ASSISTANT)
            .where(ChatMessage.created_at >= user_msg.created_at)
            .order_by(ChatMessage.created_at.asc())
            .limit(1)
        )
        if next_user_created_at is not None:
            assistant_stmt = assistant_stmt.where(
                ChatMessage.created_at < next_user_created_at
            )
        return (await self._db.execute(assistant_stmt)).scalars().first()

    async def _build_success_response_from_run(
        self,
        *,
        session_id: uuid.UUID,
        run: AgentRun,
        user_message_id: uuid.UUID | None = None,
    ) -> ChatAnswerResponse:
        assistant_msg = await self._get_assistant_message_for_user_message(
            session_id=session_id,
            user_message_id=user_message_id,
        )
        if assistant_msg is None:
            raise AppError(
                code="CHAT_REQUEST_STATE_INVALID",
                message="重复请求对应运行已完成，但缺少助手消息记录",
                status_code=409,
                details={"run_id": str(run.id)},
            )
        evidence = await self._list_run_evidence(run.id)
        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=evidence,
            stage_summaries=run.stage_summaries
            if isinstance(run.stage_summaries, dict)
            else None,
            metrics=run.metrics if isinstance(run.metrics, dict) else None,
            run=AgentRunRead.model_validate(run),
        )

    @staticmethod
    def _serialize_external_evidence_locator(item: EvidenceItem) -> dict[str, Any] | None:
        locator = dict(item.locator) if isinstance(item.locator, dict) else {}
        meta: dict[str, str] = {}
        if item.source_excerpt:
            meta["source_excerpt"] = item.source_excerpt
        if item.citation_id:
            meta["citation_id"] = item.citation_id
        if item.citation_title:
            meta["citation_title"] = item.citation_title
        if item.citation_page_hint:
            meta["citation_page_hint"] = item.citation_page_hint
        if item.citation_source:
            meta["citation_source"] = item.citation_source
        if meta:
            locator[_EXTERNAL_EVIDENCE_META_KEY] = meta
        return locator or None

    @staticmethod
    def _evidence_item_from_row(row: Evidence) -> EvidenceItem:
        locator = dict(row.locator) if isinstance(row.locator, dict) else None
        meta: dict[str, Any] | None = None
        if isinstance(locator, dict):
            raw_meta = locator.get(_EXTERNAL_EVIDENCE_META_KEY)
            if isinstance(raw_meta, dict):
                meta = dict(raw_meta)
                locator = dict(locator)
                locator.pop(_EXTERNAL_EVIDENCE_META_KEY, None)
        return EvidenceItem(
            source_kind=row.source_kind,
            kb_id=row.kb_id,
            material_id=row.material_id,
            chunk_id=row.chunk_id,
            locator=locator,
            excerpt=row.excerpt,
            source_excerpt=str(meta.get("source_excerpt") or "").strip() or None
            if isinstance(meta, dict)
            else None,
            citation_id=str(meta.get("citation_id") or "").strip() or None
            if isinstance(meta, dict)
            else None,
            citation_title=str(meta.get("citation_title") or "").strip() or None
            if isinstance(meta, dict)
            else None,
            citation_page_hint=str(meta.get("citation_page_hint") or "").strip() or None
            if isinstance(meta, dict)
            else None,
            citation_source=str(meta.get("citation_source") or "").strip() or None
            if isinstance(meta, dict)
            else None,
        )

    async def _list_run_evidence(self, run_id: uuid.UUID) -> list[EvidenceItem]:
        stmt = (
            select(Evidence)
            .where(Evidence.run_id == run_id)
            .order_by(Evidence.created_at.asc())
        )
        rows = list((await self._db.execute(stmt)).scalars().all())
        return [self._evidence_item_from_row(row) for row in rows]

    async def _persist_external_evidence(
        self,
        run_id: uuid.UUID,
        items: list[EvidenceItem],
    ) -> None:
        for item in items:
            excerpt = str(item.excerpt or "").strip()
            if not excerpt:
                continue
            self._db.add(
                Evidence(
                    run_id=run_id,
                    source_kind=EvidenceSourceKind.EXTERNAL,
                    kb_id=None,
                    material_id=None,
                    chunk_id=None,
                    locator=self._serialize_external_evidence_locator(item),
                    excerpt=excerpt[:500],
                )
            )

    async def get_pending_tool_approval(
        self,
        *,
        session: ChatSession,
        run: AgentRun | None = None,
    ) -> ChatPendingToolApprovalResponse | None:
        current_run = run or await self._get_running_general_run(session_id=session.id)
        if current_run is None:
            return None

        checkpoint_tuple = await CheckpointManager.get_state(str(session.id))
        if checkpoint_tuple is None:
            return None
        pending_interrupts_raw = _extract_pending_interrupts(checkpoint_tuple.pending_writes)
        if not pending_interrupts_raw:
            return None

        try:
            _, tool_meta_by_name = await self._load_tool_registry_for_session(
                session=session
            )
        except Exception:
            logger.warning(
                "Failed to load tool registry while recovering pending approvals; fallback to name parsing",
                extra={"session_id": str(session.id), "run_id": str(current_run.id)},
            )
            tool_meta_by_name = {}
        pending_interrupts = self._build_pending_interrupt_approvals(
            pending_interrupts_raw,
            tool_meta_by_name,
        )
        return ChatPendingToolApprovalResponse(
            thread_id=str(session.id),
            pending_interrupts=[
                PendingInterruptApproval(
                    interrupt_id=item["interrupt_id"],
                    message=item.get("message"),
                    pending_tool_calls=[
                        PendingToolCall.model_validate(call)
                        for call in item.get("pending_tool_calls", [])
                        if isinstance(call, dict)
                    ],
                )
                for item in pending_interrupts
                if isinstance(item, dict)
            ],
            run=AgentRunRead.model_validate(current_run),
        )

    async def _replay_dedup_request(
        self,
        *,
        session: ChatSession,
        dedup: ChatRequestDedup,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        bound = dedup if dedup.run_id is not None else await self._wait_for_dedup_binding(dedup=dedup)
        if bound is None or bound.run_id is None:
            raise AppError(
                code="CHAT_REQUEST_STATE_INVALID",
                message="重复请求对应运行尚未初始化，请稍后重试",
                status_code=409,
                details={
                    "session_id": str(session.id),
                    "client_request_id": dedup.client_request_id,
                },
            )

        run = await self._db.get(AgentRun, bound.run_id)
        if run is None or run.session_id != session.id:
            raise AppError(
                code="CHAT_REQUEST_STATE_INVALID",
                message="重复请求对应运行记录不存在",
                status_code=409,
                details={
                    "session_id": str(session.id),
                    "client_request_id": bound.client_request_id,
                    "run_id": str(bound.run_id),
                },
            )

        if run.status == AgentRunStatus.SUCCEEDED:
            return await self._build_success_response_from_run(
                session_id=session.id,
                run=run,
                user_message_id=bound.user_message_id,
            )

        if run.status == AgentRunStatus.RUNNING:
            pending = await self.get_pending_tool_approval(session=session, run=run)
            if pending is not None:
                return pending

            terminal = await self._wait_for_run_terminal(run_id=run.id)
            if terminal is not None and terminal.status == AgentRunStatus.SUCCEEDED:
                return await self._build_success_response_from_run(
                    session_id=session.id,
                    run=terminal,
                    user_message_id=bound.user_message_id,
                )
            if terminal is not None and terminal.status == AgentRunStatus.RUNNING:
                raise AppError(
                    code="CHAT_REQUEST_DUPLICATED",
                    message="请求已受理并正在处理中，请稍后刷新会话状态",
                    status_code=409,
                    details={
                        "run_id": str(run.id),
                        "client_request_id": bound.client_request_id,
                    },
                )

        raise AppError(
            code="CHAT_REQUEST_DUPLICATED",
            message="请求已受理且运行未成功完成，请重新发送",
            status_code=409,
            details={
                "run_id": str(run.id),
                "status": run.status.value,
                "client_request_id": bound.client_request_id,
            },
        )

    async def _load_history(
        self, session_id: uuid.UUID, limit: int | None
    ) -> list[AnyMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit * 2)
        result = await self._db.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()
        filtered = [m for m in messages if not self._is_summary_message(m)]
        if limit is not None and len(filtered) > limit:
            filtered = filtered[-limit:]
        history: list[AnyMessage] = []
        for msg in filtered:
            if msg.role == MessageRole.SYSTEM:
                history.append(SystemMessage(content=msg.content))
                continue
            if msg.role == MessageRole.ASSISTANT:
                response_id = (
                    str((msg.meta or {}).get("response_id")).strip()
                    if isinstance(msg.meta, dict)
                    and isinstance((msg.meta or {}).get("response_id"), str)
                    and str((msg.meta or {}).get("response_id")).strip()
                    else ""
                )
                if response_id:
                    history.append(
                        AIMessage(
                            content=msg.content,
                            response_metadata={"id": response_id},
                        )
                    )
                else:
                    history.append(AIMessage(content=msg.content))
                continue
            history.append(HumanMessage(content=msg.content))
        return history

    @staticmethod
    def _is_summary_message(msg: ChatMessage) -> bool:
        return bool((msg.meta or {}).get(SUMMARY_META_FLAG))

    def _build_summary_trigger(self):
        if self._settings.llm_max_input_tokens:
            return SUMMARY_TRIGGER
        triggers: list[tuple[str, int]] = []
        min_messages = self._settings.summary_trigger_min_messages
        min_tokens = self._settings.summary_trigger_min_tokens
        if min_messages > 0:
            triggers.append(("messages", min_messages))
        if min_tokens > 0:
            triggers.append(("tokens", min_tokens))
        if not triggers:
            return ("messages", SUMMARY_KEEP[1])
        return triggers[0] if len(triggers) == 1 else triggers

    @staticmethod
    def _map_llm_exception(exc: Exception) -> AppError | None:
        """将 OpenAI 兼容端点的上游异常映射为可预期的 AppError。"""
        mod = exc.__class__.__module__ or ""
        if not mod.startswith("openai"):
            return None
        exc_type = type(exc).__name__
        if exc_type == "APITimeoutError":
            return AppError(
                code="LLM_UPSTREAM_TIMEOUT",
                message="上游大模型服务响应超时，请稍后重试；若频繁出现，请在模型配置中调大超时时间或关闭思考模式",
                status_code=504,
                details={"exc_type": exc_type},
            )
        if exc_type == "APIConnectionError":
            return AppError(
                code="LLM_CONNECTION_ERROR",
                message="大模型服务连接失败，请检查 Base URL、网络连通性或上游服务状态",
                status_code=503,
                details={"exc_type": exc_type},
            )

        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

        if isinstance(status_code, int):
            if status_code == 404 and GeneralChatService._is_previous_response_not_found_error(
                exc
            ):
                return AppError(
                    code="CHAT_REPLAY_STATE_EXPIRED",
                    message="对话状态已过期，请重试当前问题",
                    status_code=409,
                    details={"upstream_status_code": status_code},
                )
            if status_code in {401, 403}:
                return AppError(
                    code="LLM_AUTH_ERROR",
                    message="大模型服务鉴权失败，请前往“模型配置”页面检查 API Key / Base URL 配置",
                    status_code=500,
                    details={"upstream_status_code": status_code},
                )
            if status_code == 429:
                return AppError(
                    code="LLM_RATE_LIMITED",
                    message="大模型服务请求过于频繁，请稍后重试",
                    status_code=503,
                    details={"upstream_status_code": status_code},
                )
            if status_code >= 500:
                return AppError(
                    code="LLM_UPSTREAM_ERROR",
                    message="上游大模型服务暂时不可用，请稍后重试",
                    status_code=503,
                    details={"upstream_status_code": status_code},
                )

        return None

    @staticmethod
    def _build_agent_messages(
        history: list[AnyMessage], user_content: str
    ) -> list[AnyMessage]:
        messages = list(history)
        messages.append(HumanMessage(content=user_content))
        return messages

    @staticmethod
    def _message_text_for_metrics(message: object) -> str:
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        text = extract_text_content(content, include_output_text=True)
        if text:
            return text
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        return str(content)

    def _resolve_replay_decision(self) -> ReplayDecision:
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=self._settings)
        try:
            provider_cfg = snapshot.active_provider_config()
        except RuntimeError as exc:
            raise ModelConfigIncompleteError(
                "模型配置不完整：没有可用的已启用供应商，请前往模型配置页面补全"
            ) from exc
        configured_mode = self._settings.general_chat_replay_mode
        decision = decide_replay_mode(
            configured_mode=self._settings.general_chat_replay_mode,
            provider=provider_cfg.provider,
            thinking_enabled=provider_cfg.thinking_enabled,
        )
        if (
            configured_mode == ReplayMode.AUTO.value
            and decision.mode == ReplayMode.RESPONSE_ID
            and provider_cfg.provider == ModelProvider.OPENAI
            and not self._supports_openai_response_replay(provider_cfg.base_url)
        ):
            logger.info(
                "General chat replay auto-downgraded to manual for non-OpenAI-compatible base_url",
                extra={"base_url": provider_cfg.base_url},
            )
            return self._manual_replay_decision()
        return decision

    @staticmethod
    def _supports_openai_response_replay(base_url: str | None) -> bool:
        if not isinstance(base_url, str) or not base_url.strip():
            return False
        try:
            parsed = urlparse(base_url.strip())
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname == "api.openai.com":
            return True
        if hostname.endswith(".openai.azure.com"):
            return True
        return False

    def _requires_assistant_response_id_for_replay(self) -> bool:
        return self._resolve_replay_decision().require_assistant_response_id

    def _sanitize_history_for_replay(
        self,
        history: list[AnyMessage],
        *,
        require_assistant_response_id: bool,
    ) -> list[AnyMessage]:
        if not history or not require_assistant_response_id:
            return history

        dropped = 0
        kept: list[AnyMessage] = []
        for msg in history:
            if isinstance(msg, AIMessage) and extract_response_id(msg) is None:
                dropped += 1
                continue
            kept.append(msg)

        if dropped:
            logger.warning(
                "Dropped assistant history without response_id for Responses replay safety",
                extra={"dropped_messages": dropped},
            )
        return kept

    @staticmethod
    def _drop_trailing_user_message(
        history: list[AnyMessage],
        *,
        user_content: str,
    ) -> list[AnyMessage]:
        if not history:
            return history
        last = history[-1]
        if not isinstance(last, HumanMessage):
            return history
        if last.content != user_content:
            return history
        return history[:-1]

    @staticmethod
    def _build_pending_interrupt_approvals(
        interrupts: list[object],
        tool_meta_by_name: dict[str, Any],
    ) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        for entry in _build_interrupt_entries(interrupts):
            pending_tool_calls = build_pending_tool_calls(
                entry["action_requests"],
                tool_meta_by_name,
            )
            approvals.append(
                {
                    "interrupt_id": entry["interrupt_id"],
                    "message": entry["message"],
                    "pending_tool_calls": pending_tool_calls,
                    "action_requests": entry["action_requests"],
                }
            )
        return approvals

    @staticmethod
    def _build_interrupt_stage_summary(
        pending_interrupts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        interrupt_ids = [
            str(item["interrupt_id"])
            for item in pending_interrupts
            if isinstance(item.get("interrupt_id"), str)
        ]
        tool_count = sum(
            len(item.get("pending_tool_calls", []))
            for item in pending_interrupts
            if isinstance(item.get("pending_tool_calls"), list)
        )
        return {
            "pending": True,
            "tool_count": tool_count,
            "interrupt_count": len(interrupt_ids),
            "interrupt_ids": interrupt_ids,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _to_pending_interrupt_models(
        pending_interrupts: list[dict[str, Any]],
    ) -> list[PendingInterruptApproval]:
        return [
            PendingInterruptApproval(
                interrupt_id=item["interrupt_id"],
                message=item.get("message"),
                pending_tool_calls=[
                    PendingToolCall.model_validate(call)
                    for call in item.get("pending_tool_calls", [])
                    if isinstance(call, dict)
                ],
            )
            for item in pending_interrupts
            if isinstance(item, dict)
        ]

    async def _recover_stream_pending_tool_approval(
        self,
        *,
        thread_id: str,
        run: AgentRun,
        stream_state: StreamState,
        tool_meta_by_name: dict[str, Any],
        started_at: datetime,
        replay_metrics: dict[str, object],
        preserve_existing_metrics: bool = False,
    ) -> ChatPendingToolApprovalResponse | None:
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        if checkpoint_tuple is None:
            return None
        pending_interrupts_raw = _extract_pending_interrupts(
            checkpoint_tuple.pending_writes
        )
        if not pending_interrupts_raw:
            return None

        pending_interrupts = self._build_pending_interrupt_approvals(
            pending_interrupts_raw,
            tool_meta_by_name,
        )
        if not pending_interrupts:
            return None

        context_metrics = self._build_context_metrics(stream_state.messages)
        run.stage_summaries = {
            "tool_approval": self._build_interrupt_stage_summary(pending_interrupts)
        }

        next_metrics = {
            "latency_ms": int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
            "context": context_metrics,
            **replay_metrics,
            **(stream_state.metrics if isinstance(stream_state.metrics, dict) else {}),
        }
        if preserve_existing_metrics and isinstance(run.metrics, dict):
            next_metrics = {**run.metrics, **next_metrics}
        run.metrics = next_metrics

        await self._db.commit()
        await self._db.refresh(run)
        return ChatPendingToolApprovalResponse(
            thread_id=thread_id,
            pending_interrupts=self._to_pending_interrupt_models(pending_interrupts),
            run=AgentRunRead.model_validate(run),
        )

    @staticmethod
    def _build_resume_decisions_payload(
        pending_interrupts: list[dict[str, Any]],
        approval: ToolApprovalRequest,
    ) -> dict[str, Any]:
        pending_ids = [
            item["interrupt_id"]
            for item in pending_interrupts
            if isinstance(item.get("interrupt_id"), str)
        ]
        requested_map = {item.interrupt_id: item for item in approval.interrupts}
        if len(requested_map) != len(approval.interrupts):
            raise AppError(
                code="TOOL_APPROVAL_PAYLOAD_INVALID",
                message="审批请求包含重复的 interrupt_id",
                status_code=400,
            )

        missing = [interrupt_id for interrupt_id in pending_ids if interrupt_id not in requested_map]
        pending_id_set = set(pending_ids)
        extra = [interrupt_id for interrupt_id in requested_map if interrupt_id not in pending_id_set]
        if missing or extra:
            raise AppError(
                code="TOOL_APPROVAL_PAYLOAD_INVALID",
                message="审批请求与当前待审批中断不匹配",
                status_code=400,
                details={"missing_interrupt_ids": missing, "extra_interrupt_ids": extra},
            )

        decision_map: dict[str, dict[str, Any]] = {}
        for item in pending_interrupts:
            interrupt_id = item.get("interrupt_id")
            if not isinstance(interrupt_id, str):
                continue
            action_requests = item.get("action_requests")
            if not isinstance(action_requests, list):
                action_requests = []
            batch = requested_map.get(interrupt_id)
            if batch is None:
                raise AppError(
                    code="TOOL_APPROVAL_PAYLOAD_INVALID",
                    message="审批请求缺少待审批中断",
                    status_code=400,
                )
            if len(batch.decisions) != len(action_requests):
                raise AppError(
                    code="TOOL_APPROVAL_PAYLOAD_INVALID",
                    message="审批决策数量与工具调用数量不一致",
                    status_code=400,
                    details={
                        "interrupt_id": interrupt_id,
                        "expected": len(action_requests),
                        "actual": len(batch.decisions),
                    },
                )
            decision_map[interrupt_id] = {
                "decisions": [
                    decision.model_dump(mode="json", exclude_none=True)
                    for decision in batch.decisions
                ]
            }

        if len(decision_map) == 1:
            only = next(iter(decision_map.values()))
            return {"decisions": only["decisions"]}
        return decision_map

    async def _get_running_general_run(
        self,
        *,
        session_id: uuid.UUID,
        exclude_run_id: uuid.UUID | None = None,
    ) -> AgentRun | None:
        stmt = select(AgentRun).where(
            AgentRun.session_id == session_id,
            AgentRun.run_type == AgentRunType.GENERAL_ANSWER,
            AgentRun.status == AgentRunStatus.RUNNING,
        )
        if exclude_run_id is not None:
            stmt = stmt.where(AgentRun.id != exclude_run_id)
        stmt = stmt.order_by(AgentRun.created_at.desc()).limit(1)
        result = await self._db.execute(stmt)
        return result.scalars().first()

    async def _ensure_no_running_general_run(self, *, session_id: uuid.UUID) -> None:
        await self._db.execute(
            select(ChatSession.id)
            .where(ChatSession.id == session_id)
            .with_for_update()
        )
        running = await self._get_running_general_run(session_id=session_id)
        if running is None:
            return
        raise AppError(
            code="CHAT_RUN_CONFLICT",
            message="当前会话已有运行中的普通代理任务，请先完成审批或等待结束",
            status_code=409,
            details={"run_id": str(running.id)},
        )

    async def _ensure_resume_target_valid(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
    ) -> None:
        await self._db.execute(
            select(ChatSession.id)
            .where(ChatSession.id == session.id)
            .with_for_update()
        )
        running = await self._get_running_general_run(
            session_id=session.id,
            exclude_run_id=None,
        )
        if running is None:
            raise AppError(
                code="CHAT_RUN_NOT_RUNNING",
                message="运行记录已完成或已失败",
                status_code=400,
            )
        if running.id != run.id:
            raise AppError(
                code="CHAT_RUN_CONFLICT",
                message="当前会话已有其他运行中的普通代理任务",
                status_code=409,
                details={"run_id": str(running.id)},
            )
        stage_summaries = run.stage_summaries if isinstance(run.stage_summaries, dict) else {}
        tool_approval = (
            stage_summaries.get("tool_approval")
            if isinstance(stage_summaries.get("tool_approval"), dict)
            else {}
        )
        if tool_approval.get("pending") is not True:
            raise AppError(
                code="NO_PENDING_APPROVAL",
                message="当前会话没有待审批的工具调用",
                status_code=400,
            )

    @staticmethod
    def _extract_upstream_error_message(exc: Exception) -> str:
        message = str(exc)
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error_obj = body.get("error")
            if isinstance(error_obj, dict):
                error_message = error_obj.get("message")
                if isinstance(error_message, str) and error_message.strip():
                    return error_message.strip()
        return message

    @staticmethod
    def _is_previous_response_not_found_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
        if status_code != 404:
            return False
        message = GeneralChatService._extract_upstream_error_message(exc).lower()
        return "response with id" in message and "not found" in message

    @classmethod
    def _should_recover_from_response_not_found(
        cls,
        exc: Exception,
        replay_decision: ReplayDecision,
    ) -> bool:
        return replay_decision.allow_recovery and cls._is_previous_response_not_found_error(
            exc
        )

    @staticmethod
    def _manual_replay_decision() -> ReplayDecision:
        return ReplayDecision(
            mode=ReplayMode.MANUAL,
            use_previous_response_id=False,
            require_assistant_response_id=False,
            allow_recovery=False,
        )

    @staticmethod
    def _build_replay_metrics(
        replay_decision: ReplayDecision,
        *,
        recovered: bool = False,
        recovery_reason: str | None = None,
    ) -> dict[str, object]:
        replay: dict[str, object] = {
            "mode": replay_decision.mode.value,
            "used_previous_response_id": replay_decision.use_previous_response_id,
            "recovered": recovered,
        }
        if recovery_reason:
            replay["recovery_reason"] = recovery_reason
        return {"replay": replay}

    def _build_context_metrics(self, messages: list[object]) -> dict[str, dict]:
        total_tokens = 0
        total_chars = 0
        for msg in messages:
            text = self._message_text_for_metrics(msg)
            total_tokens += count_tokens_approximately(text)
            total_chars += len(text)

        history_usage = {
            "tokens": total_tokens,
            "chars": total_chars,
            "messages": len(messages),
        }
        history_truncation = {
            "truncated": False,
            "dropped_messages": 0,
            "dropped_tokens": 0,
        }
        return self._context_builder.build_metrics(
            history_usage={"history": history_usage},
            history_truncation={"history": history_truncation},
        )

    async def answer(
        self,
        *,
        session: ChatSession,
        user_content: str,
        client_request_id: str | None = None,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        """处理用户问题并生成答案（使用 create_agent）。"""
        normalized_client_request_id = self._normalize_client_request_id(client_request_id)
        dedup_record: ChatRequestDedup | None = None
        if normalized_client_request_id:
            dedup_record, claimed = await self._claim_request_dedup(
                session_id=session.id,
                client_request_id=normalized_client_request_id,
            )
            if not claimed:
                if dedup_record is None:  # pragma: no cover - defensive
                    raise RuntimeError("Missing dedup record for replay path")
                return await self._replay_dedup_request(session=session, dedup=dedup_record)

        try:
            await self._ensure_no_running_general_run(session_id=session.id)
        except Exception:
            if dedup_record is not None:
                await self._delete_unbound_request_dedup(dedup=dedup_record)
            raise
        started_at = datetime.now(timezone.utc)
        thread_id = str(session.id)
        replay_decision = self._resolve_replay_decision()
        require_assistant_response_id = replay_decision.require_assistant_response_id
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        history: list[AnyMessage] = []
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages")
            if checkpoint_messages_require_reset(
                existing_messages,
                require_assistant_response_id=require_assistant_response_id,
            ):
                logger.warning(
                    "Resetting incompatible general chat checkpoint",
                    extra={
                        "thread_id": thread_id,
                        "require_assistant_response_id": require_assistant_response_id,
                    },
                )
                await CheckpointManager.delete_thread(thread_id)
                checkpoint_tuple = None
                existing_messages = None
        if checkpoint_tuple is None or not isinstance(existing_messages, list) or not existing_messages:
            history = await self._load_history(session.id, limit=None)
        original_history = list(history)

        # 保存用户消息
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=user_content,
        )
        self._db.add(user_msg)

        # 创建运行记录
        run = AgentRun(
            run_type=AgentRunType.GENERAL_ANSWER,
            session_id=session.id,
            question=user_content,
            selected_kb_ids=None,
            allow_external=session.allow_external,
            mode=session.mode,
            status=AgentRunStatus.RUNNING,
            started_at=started_at,
        )
        self._db.add(run)
        try:
            await self._db.flush()
            if dedup_record is not None:
                dedup_record.run_id = run.id
                dedup_record.user_message_id = user_msg.id
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            if dedup_record is not None:
                await self._delete_unbound_request_dedup(dedup=dedup_record)
            raise
        set_run_id(str(run.id))

        try:
            # 统一工具注册（内置 + MCP）
            tools, tool_meta_by_name = await self._open_runtime_tool_registry_for_session(
                session=session
            )
            hitl_interrupt_on = build_hitl_interrupt_on(tool_meta_by_name)

            # 构造初始 messages（历史 + 用户问题）
            system_prompt = self._prompts.render_with_few_shot("general_chat/system")
            first_history = self._sanitize_history_for_replay(
                original_history,
                require_assistant_response_id=require_assistant_response_id,
            )
            config = CheckpointManager.make_config(thread_id)
            replay_metrics = self._build_replay_metrics(replay_decision)

            try:
                chat_model = create_chat_model(
                    settings=self._settings,
                    use_previous_response_id=replay_decision.use_previous_response_id,
                )
                messages = self._build_agent_messages(first_history, user_content)
                agent = build_general_chat_agent(
                    chat_model=chat_model,
                    tools=tools,
                    system_prompt=system_prompt,
                    summary_trigger=self._build_summary_trigger(),
                    hitl_interrupt_on=hitl_interrupt_on,
                )
                result = await agent.ainvoke({"messages": messages}, config)
            except Exception as invoke_exc:
                if not self._should_recover_from_response_not_found(
                    invoke_exc, replay_decision
                ):
                    raise
                logger.warning(
                    "Recovering from previous_response_id 404 by resetting thread and replaying manually",
                    extra={"thread_id": thread_id},
                )
                await CheckpointManager.delete_thread(thread_id)

                recovery_decision = self._manual_replay_decision()
                recovery_history = await self._load_history(session.id, limit=None)
                recovery_history = self._drop_trailing_user_message(
                    recovery_history,
                    user_content=user_content,
                )
                recovery_model = create_chat_model(
                    settings=self._settings,
                    use_previous_response_id=recovery_decision.use_previous_response_id,
                )
                recovery_messages = self._build_agent_messages(
                    recovery_history,
                    user_content,
                )
                recovery_agent = build_general_chat_agent(
                    chat_model=recovery_model,
                    tools=tools,
                    system_prompt=system_prompt,
                    summary_trigger=self._build_summary_trigger(),
                    hitl_interrupt_on=hitl_interrupt_on,
                )
                result = await recovery_agent.ainvoke(
                    {"messages": recovery_messages},
                    config,
                )
                replay_metrics = self._build_replay_metrics(
                    recovery_decision,
                    recovered=True,
                    recovery_reason="previous_response_id_not_found",
                )

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            interrupts = result.get("__interrupt__")
            if isinstance(interrupts, list) and interrupts:
                pending_interrupts = self._build_pending_interrupt_approvals(
                    interrupts, tool_meta_by_name
                )
                context_metrics = self._build_context_metrics(
                    result.get("messages") if isinstance(result.get("messages"), list) else []
                )

                run.stage_summaries = {
                    "tool_approval": self._build_interrupt_stage_summary(
                        pending_interrupts
                    ),
                }
                metrics = result.get("metrics")
                if not isinstance(metrics, dict):
                    metrics = {}
                run.metrics = {
                    "latency_ms": int(
                        (datetime.now(timezone.utc) - started_at).total_seconds()
                        * 1000
                    ),
                    "context": context_metrics,
                    **replay_metrics,
                    **metrics,
                }

                await self._db.commit()
                await self._db.refresh(run)

                return ChatPendingToolApprovalResponse(
                    thread_id=thread_id,
                    pending_interrupts=[
                        PendingInterruptApproval(
                            interrupt_id=item["interrupt_id"],
                            message=item.get("message"),
                            pending_tool_calls=[
                                PendingToolCall.model_validate(call)
                                for call in item.get("pending_tool_calls", [])
                                if isinstance(call, dict)
                            ],
                        )
                        for item in pending_interrupts
                        if isinstance(item, dict)
                    ],
                    run=AgentRunRead.model_validate(run),
                )

            return await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                result=result,
                replay_metrics=replay_metrics,
            )

        except Exception as e:
            await self._persist_failed_run(run=run, error=e)

            mapped = self._map_llm_exception(e)
            if mapped is not None:
                logger.warning(
                    "LLM 调用失败",
                    extra={
                        "exc_type": type(e).__name__,
                        "upstream_status_code": getattr(e, "status_code", None),
                    },
                )
                raise mapped from e

            raise
        finally:
            await self._close_runtime_tool_registry()
            set_run_id(None)

    async def answer_stream(
        self,
        *,
        session: ChatSession,
        user_content: str,
        request: object | None = None,
        client_request_id: str | None = None,
    ) -> Any:
        """处理用户问题并生成答案（流式 SSE）。"""
        normalized_client_request_id = self._normalize_client_request_id(client_request_id)
        dedup_record: ChatRequestDedup | None = None
        if normalized_client_request_id:
            dedup_record, claimed = await self._claim_request_dedup(
                session_id=session.id,
                client_request_id=normalized_client_request_id,
            )
            if not claimed:
                if dedup_record is None:  # pragma: no cover - defensive
                    raise RuntimeError("Missing dedup record for replay path")
                try:
                    replay = await self._replay_dedup_request(
                        session=session,
                        dedup=dedup_record,
                    )
                except AppError as app_error:
                    yield "error", {
                        "code": app_error.code,
                        "message": app_error.message,
                        "details": app_error.details,
                    }
                    return
                yield "meta", {
                    "run_id": str(replay.run.id),
                    "session_id": str(session.id),
                    "session_type": session.session_type.value,
                    "thread_id": str(session.id),
                    "mode": session.mode.value,
                    "dedup_hit": True,
                }
                if replay.status == "pending_tool_approval":
                    yield "interrupt", replay.model_dump(mode="json")
                else:
                    yield "final", replay.model_dump(mode="json")
                return

        try:
            await self._ensure_no_running_general_run(session_id=session.id)
        except Exception:
            if dedup_record is not None:
                await self._delete_unbound_request_dedup(dedup=dedup_record)
            raise
        started_at = datetime.now(timezone.utc)
        thread_id = str(session.id)
        try:
            replay_decision = self._resolve_replay_decision()
        except ModelConfigIncompleteError as exc:
            yield "error", {
                "code": "MODEL_CONFIG_INCOMPLETE",
                "message": str(exc),
            }
            return
        require_assistant_response_id = replay_decision.require_assistant_response_id
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        history: list[AnyMessage] = []
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages")
            if checkpoint_messages_require_reset(
                existing_messages,
                require_assistant_response_id=require_assistant_response_id,
            ):
                logger.warning(
                    "Resetting incompatible general chat checkpoint",
                    extra={
                        "thread_id": thread_id,
                        "require_assistant_response_id": require_assistant_response_id,
                    },
                )
                await CheckpointManager.delete_thread(thread_id)
                checkpoint_tuple = None
                existing_messages = None
        if checkpoint_tuple is None or not isinstance(existing_messages, list) or not existing_messages:
            history = await self._load_history(session.id, limit=None)
        original_history = list(history)

        # 保存用户消息
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=user_content,
        )
        self._db.add(user_msg)

        # 创建运行记录
        run = AgentRun(
            run_type=AgentRunType.GENERAL_ANSWER,
            session_id=session.id,
            question=user_content,
            selected_kb_ids=None,
            allow_external=session.allow_external,
            mode=session.mode,
            status=AgentRunStatus.RUNNING,
            started_at=started_at,
        )
        self._db.add(run)
        try:
            await self._db.flush()
            if dedup_record is not None:
                dedup_record.run_id = run.id
                dedup_record.user_message_id = user_msg.id
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            if dedup_record is not None:
                await self._delete_unbound_request_dedup(dedup=dedup_record)
            raise
        set_run_id(str(run.id))

        try:
            # 统一工具注册（内置 + MCP）
            tools, tool_meta_by_name = await self._open_runtime_tool_registry_for_session(
                session=session
            )
            hitl_interrupt_on = build_hitl_interrupt_on(tool_meta_by_name)

            system_prompt = self._prompts.render_with_few_shot("general_chat/system")
            config = CheckpointManager.make_config(thread_id)
            replay_metrics = self._build_replay_metrics(replay_decision)

            # SSE：meta 事件
            yield "meta", {
                "run_id": str(run.id),
                "session_id": str(session.id),
                "session_type": session.session_type.value,
                "thread_id": thread_id,
                "mode": session.mode.value,
            }

            current_decision = replay_decision
            attempt = 0
            while True:
                attempt_history = self._sanitize_history_for_replay(
                    original_history,
                    require_assistant_response_id=current_decision.require_assistant_response_id,
                )
                attempt_messages = self._build_agent_messages(
                    attempt_history,
                    user_content,
                )
                attempt_checkpoint_messages: list[object] = []
                if attempt == 0 and checkpoint_tuple is not None:
                    checkpoint_values = (checkpoint_tuple.checkpoint or {}).get(
                        "channel_values", {}
                    )
                    stored_messages = checkpoint_values.get("messages")
                    if isinstance(stored_messages, list):
                        attempt_checkpoint_messages = list(stored_messages)

                chat_model = create_chat_model(
                    settings=self._settings,
                    use_previous_response_id=current_decision.use_previous_response_id,
                )
                agent = build_general_chat_agent(
                    chat_model=chat_model,
                    tools=tools,
                    system_prompt=system_prompt,
                    summary_trigger=self._build_summary_trigger(),
                    hitl_interrupt_on=hitl_interrupt_on,
                )
                stream_state = StreamState(
                    messages=[*attempt_checkpoint_messages, *list(attempt_messages)],
                    pending_tool_calls=[],
                    stage_summaries={},
                    metrics={},
                )
                emitted_payload = False

                try:
                    async for mode, chunk in agent.astream(
                        {"messages": attempt_messages},
                        config,
                        stream_mode=["messages", "updates"],
                    ):
                        if request is not None:
                            is_disconnected = getattr(request, "is_disconnected", None)
                            if callable(is_disconnected) and await is_disconnected():
                                run.status = AgentRunStatus.CANCELED
                                run.finished_at = datetime.now(timezone.utc)
                                await self._db.commit()
                                return

                        if mode == "messages":
                            token, _meta = chunk
                            deltas = extract_stream_delta(
                                token,
                                _meta if isinstance(_meta, dict) else None,
                            )
                            if deltas:
                                emitted_payload = True
                                node_name = (
                                    _meta.get("langgraph_node")
                                    if isinstance(_meta, dict)
                                    and isinstance(_meta.get("langgraph_node"), str)
                                    else None
                                )
                                yield "messages", {
                                    "run_id": str(run.id),
                                    "node": node_name,
                                    "deltas": [delta.to_dict() for delta in deltas],
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                }
                            continue

                        if mode == "updates" and isinstance(chunk, dict):
                            interrupts = apply_updates_chunk(stream_state, chunk)
                            if interrupts:
                                pending_interrupts = self._build_pending_interrupt_approvals(
                                    interrupts,
                                    tool_meta_by_name,
                                )
                                context_metrics = self._build_context_metrics(
                                    stream_state.messages
                                )

                                run.stage_summaries = {
                                    "tool_approval": self._build_interrupt_stage_summary(
                                        pending_interrupts
                                    ),
                                }
                                run.metrics = {
                                    "latency_ms": int(
                                        (datetime.now(timezone.utc) - started_at).total_seconds()
                                        * 1000
                                    ),
                                    "context": context_metrics,
                                    **replay_metrics,
                                    **(
                                        stream_state.metrics
                                        if isinstance(stream_state.metrics, dict)
                                        else {}
                                    ),
                                }
                                await self._db.commit()
                                await self._db.refresh(run)

                                response = ChatPendingToolApprovalResponse(
                                    thread_id=thread_id,
                                    pending_interrupts=self._to_pending_interrupt_models(
                                        pending_interrupts
                                    ),
                                    run=AgentRunRead.model_validate(run),
                                )
                                emitted_payload = True
                                yield "interrupt", response.model_dump(mode="json")
                                return

                    pending_response = await self._recover_stream_pending_tool_approval(
                        thread_id=thread_id,
                        run=run,
                        stream_state=stream_state,
                        tool_meta_by_name=tool_meta_by_name,
                        started_at=started_at,
                        replay_metrics=replay_metrics,
                    )
                    if pending_response is not None:
                        emitted_payload = True
                        yield "interrupt", pending_response.model_dump(mode="json")
                        return

                    result = {
                        "messages": stream_state.messages,
                        "stage_summaries": stream_state.stage_summaries,
                        "metrics": stream_state.metrics,
                    }
                    final_response = await self._finalize_run(
                        session=session,
                        run=run,
                        started_at=started_at,
                        result=result,
                        replay_metrics=replay_metrics,
                    )
                    emitted_payload = True
                    yield "final", final_response.model_dump(mode="json")
                    return
                except Exception as stream_exc:
                    if (
                        attempt == 0
                        and not emitted_payload
                        and self._should_recover_from_response_not_found(
                            stream_exc, current_decision
                        )
                    ):
                        logger.warning(
                            "Recovering stream from previous_response_id 404 by resetting thread",
                            extra={"thread_id": thread_id},
                        )
                        await CheckpointManager.delete_thread(thread_id)
                        current_decision = self._manual_replay_decision()
                        replay_metrics = self._build_replay_metrics(
                            current_decision,
                            recovered=True,
                            recovery_reason="previous_response_id_not_found",
                        )
                        recovery_history = await self._load_history(session.id, limit=None)
                        original_history = self._drop_trailing_user_message(
                            recovery_history,
                            user_content=user_content,
                        )
                        checkpoint_tuple = None
                        attempt += 1
                        continue
                    raise

        except Exception as e:
            await self._persist_failed_run(run=run, error=e)

            if isinstance(e, ModelConfigIncompleteError):
                yield "error", {
                    "code": "MODEL_CONFIG_INCOMPLETE",
                    "message": str(e),
                }
                return

            mapped = self._map_llm_exception(e)
            if mapped is not None:
                logger.warning(
                    "LLM 流式调用失败",
                    extra={
                        "exc_type": type(e).__name__,
                        "upstream_status_code": getattr(e, "status_code", None),
                    },
                )
                yield "error", {
                    "code": mapped.code,
                    "message": mapped.message,
                    "details": mapped.details,
                }
                return

            yield "error", {
                "code": "CHAT_STREAM_FAILED",
                "message": str(e),
            }
        finally:
            await self._close_runtime_tool_registry()
            set_run_id(None)

    async def resume_after_tool_approval(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        approval: ToolApprovalRequest,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        """两阶段交互第 2 阶段：提交审批结果并恢复执行。"""
        set_run_id(str(run.id))
        try:
            await self._ensure_resume_target_valid(session=session, run=run)
            thread_id = str(session.id)
            checkpoint_tuple = await CheckpointManager.get_state(thread_id)
            if checkpoint_tuple is None:
                raise AppError(
                    code="CHECKPOINT_NOT_FOUND",
                    message="检查点不存在，无法恢复执行",
                    status_code=404,
                )

            pending_interrupts_raw = _extract_pending_interrupts(
                checkpoint_tuple.pending_writes
            )
            if not pending_interrupts_raw:
                raise AppError(
                    code="NO_PENDING_APPROVAL",
                    message="当前会话没有待审批的工具调用",
                    status_code=400,
                )

            # 为恢复执行重新构建 agent（状态由 checkpointer 提供）
            tools, tool_meta_by_name = await self._open_runtime_tool_registry_for_session(
                session=session
            )
            hitl_interrupt_on = build_hitl_interrupt_on(tool_meta_by_name)
            pending_interrupts = self._build_pending_interrupt_approvals(
                pending_interrupts_raw,
                tool_meta_by_name,
            )
            resume_payload = self._build_resume_decisions_payload(
                pending_interrupts,
                approval,
            )

            replay_decision = self._resolve_replay_decision()
            replay_metrics = self._build_replay_metrics(replay_decision)
            chat_model = create_chat_model(
                settings=self._settings,
                use_previous_response_id=replay_decision.use_previous_response_id,
            )

            system_prompt = self._prompts.render_with_few_shot("general_chat/system")
            agent = build_general_chat_agent(
                chat_model=chat_model,
                tools=tools,
                system_prompt=system_prompt,
                summary_trigger=self._build_summary_trigger(),
                hitl_interrupt_on=hitl_interrupt_on,
            )
            config = CheckpointManager.make_config(thread_id)
            result = await agent.ainvoke(Command(resume=resume_payload), config)

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            interrupts = result.get("__interrupt__")
            if isinstance(interrupts, list) and interrupts:
                next_pending_interrupts = self._build_pending_interrupt_approvals(
                    interrupts,
                    tool_meta_by_name,
                )
                context_metrics = self._build_context_metrics(
                    result.get("messages")
                    if isinstance(result.get("messages"), list)
                    else []
                )

                run.stage_summaries = {
                    "tool_approval": self._build_interrupt_stage_summary(
                        next_pending_interrupts
                    ),
                }
                metrics = result.get("metrics")
                if not isinstance(metrics, dict):
                    metrics = {}
                run.metrics = {
                    **(run.metrics if isinstance(run.metrics, dict) else {}),
                    "latency_ms": int(
                        (
                            datetime.now(timezone.utc)
                            - (run.started_at or datetime.now(timezone.utc))
                        ).total_seconds()
                        * 1000
                    ),
                    "context": context_metrics,
                    **replay_metrics,
                    **metrics,
                }
                await self._db.commit()
                await self._db.refresh(run)
                return ChatPendingToolApprovalResponse(
                    thread_id=thread_id,
                    pending_interrupts=[
                        PendingInterruptApproval(
                            interrupt_id=item["interrupt_id"],
                            message=item.get("message"),
                            pending_tool_calls=[
                                PendingToolCall.model_validate(call)
                                for call in item.get("pending_tool_calls", [])
                                if isinstance(call, dict)
                            ],
                        )
                        for item in next_pending_interrupts
                        if isinstance(item, dict)
                    ],
                    run=AgentRunRead.model_validate(run),
                )

            started_at = run.started_at or datetime.now(timezone.utc)
            return await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                result=result,
                replay_metrics=replay_metrics,
            )
        finally:
            await self._close_runtime_tool_registry()
            set_run_id(None)

    async def resume_after_tool_approval_stream(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        approval: ToolApprovalRequest,
        request: object | None = None,
    ) -> Any:
        """两阶段交互第 2 阶段：提交审批结果并恢复执行（流式 SSE）。"""
        set_run_id(str(run.id))
        try:
            await self._ensure_resume_target_valid(session=session, run=run)
            thread_id = str(session.id)
            checkpoint_tuple = await CheckpointManager.get_state(thread_id)
            if checkpoint_tuple is None:
                yield "error", {
                    "code": "CHECKPOINT_NOT_FOUND",
                    "message": "检查点不存在，无法恢复执行",
                }
                return

            pending_interrupts_raw = _extract_pending_interrupts(
                checkpoint_tuple.pending_writes
            )
            if not pending_interrupts_raw:
                yield "error", {
                    "code": "NO_PENDING_APPROVAL",
                    "message": "当前会话没有待审批的工具调用",
                }
                return

            # 为恢复执行重新构建 agent（状态由 checkpointer 提供）
            tools, tool_meta_by_name = await self._open_runtime_tool_registry_for_session(
                session=session
            )
            hitl_interrupt_on = build_hitl_interrupt_on(tool_meta_by_name)
            pending_interrupts = self._build_pending_interrupt_approvals(
                pending_interrupts_raw,
                tool_meta_by_name,
            )
            resume_payload = self._build_resume_decisions_payload(
                pending_interrupts,
                approval,
            )

            replay_decision = self._resolve_replay_decision()
            replay_metrics = self._build_replay_metrics(replay_decision)
            chat_model = create_chat_model(
                settings=self._settings,
                use_previous_response_id=replay_decision.use_previous_response_id,
            )

            system_prompt = self._prompts.render_with_few_shot("general_chat/system")
            agent = build_general_chat_agent(
                chat_model=chat_model,
                tools=tools,
                system_prompt=system_prompt,
                summary_trigger=self._build_summary_trigger(),
                hitl_interrupt_on=hitl_interrupt_on,
            )
            config = CheckpointManager.make_config(thread_id)

            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages", [])
            stream_state = StreamState(
                messages=list(existing_messages)
                if isinstance(existing_messages, list)
                else [],
                pending_tool_calls=[],
                stage_summaries={},
                metrics={},
            )

            yield "meta", {
                "run_id": str(run.id),
                "session_id": str(session.id),
                "session_type": session.session_type.value,
                "thread_id": thread_id,
                "mode": session.mode.value,
                "resumed": True,
            }

            async for mode, chunk in agent.astream(
                Command(resume=resume_payload),
                config,
                stream_mode=["messages", "updates"],
            ):
                if request is not None:
                    is_disconnected = getattr(request, "is_disconnected", None)
                    if callable(is_disconnected) and await is_disconnected():
                        run.status = AgentRunStatus.CANCELED
                        run.finished_at = datetime.now(timezone.utc)
                        await self._db.commit()
                        return

                if mode == "messages":
                    token, _meta = chunk
                    deltas = extract_stream_delta(
                        token,
                        _meta if isinstance(_meta, dict) else None,
                    )
                    if deltas:
                        node_name = (
                            _meta.get("langgraph_node")
                            if isinstance(_meta, dict)
                            and isinstance(_meta.get("langgraph_node"), str)
                            else None
                        )
                        yield "messages", {
                            "run_id": str(run.id),
                            "node": node_name,
                            "deltas": [delta.to_dict() for delta in deltas],
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    continue

                if mode == "updates" and isinstance(chunk, dict):
                    interrupts = apply_updates_chunk(stream_state, chunk)
                    if interrupts:
                        next_pending_interrupts = self._build_pending_interrupt_approvals(
                            interrupts,
                            tool_meta_by_name,
                        )
                        context_metrics = self._build_context_metrics(
                            stream_state.messages
                        )

                        run.stage_summaries = {
                            "tool_approval": self._build_interrupt_stage_summary(
                                next_pending_interrupts
                            ),
                        }
                        run.metrics = {
                            **(run.metrics if isinstance(run.metrics, dict) else {}),
                            "latency_ms": int(
                                (datetime.now(timezone.utc) - (run.started_at or datetime.now(timezone.utc))).total_seconds()
                                * 1000
                            ),
                            "context": context_metrics,
                            **replay_metrics,
                            **(stream_state.metrics if isinstance(stream_state.metrics, dict) else {}),
                        }
                        await self._db.commit()
                        await self._db.refresh(run)

                        response = ChatPendingToolApprovalResponse(
                            thread_id=thread_id,
                            pending_interrupts=self._to_pending_interrupt_models(
                                next_pending_interrupts
                            ),
                            run=AgentRunRead.model_validate(run),
                        )
                        yield "interrupt", response.model_dump(mode="json")
                        return

            started_at = run.started_at or datetime.now(timezone.utc)
            pending_response = await self._recover_stream_pending_tool_approval(
                thread_id=thread_id,
                run=run,
                stream_state=stream_state,
                tool_meta_by_name=tool_meta_by_name,
                started_at=started_at,
                replay_metrics=replay_metrics,
                preserve_existing_metrics=True,
            )
            if pending_response is not None:
                yield "interrupt", pending_response.model_dump(mode="json")
                return

            result = {
                "messages": stream_state.messages,
                "stage_summaries": stream_state.stage_summaries,
                "metrics": stream_state.metrics,
            }
            final_response = await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                result=result,
                replay_metrics=replay_metrics,
            )
            yield "final", final_response.model_dump(mode="json")

        except Exception as e:
            await self._persist_failed_run(run=run, error=e)

            if isinstance(e, ModelConfigIncompleteError):
                yield "error", {
                    "code": "MODEL_CONFIG_INCOMPLETE",
                    "message": str(e),
                }
                return

            mapped = self._map_llm_exception(e)
            if mapped is not None:
                logger.warning(
                    "LLM 流式恢复失败",
                    extra={
                        "exc_type": type(e).__name__,
                        "upstream_status_code": getattr(e, "status_code", None),
                    },
                )
                yield "error", {
                    "code": mapped.code,
                    "message": mapped.message,
                    "details": mapped.details,
                }
                return

            yield "error", {
                "code": "CHAT_STREAM_FAILED",
                "message": str(e),
            }
        finally:
            await self._close_runtime_tool_registry()
            set_run_id(None)

    async def _finalize_run(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        started_at: datetime,
        result: dict,
        replay_metrics: dict[str, object] | None = None,
    ) -> ChatAnswerResponse:
        messages = result.get("messages") or []
        if not isinstance(messages, list):
            messages = []

        now = datetime.now(timezone.utc)
        answer = ""
        response_id: str | None = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                # 提取纯文本回答（剥离思考段）
                answer = extract_answer_text(msg.content)
                if not answer:
                    answer = extract_message_text(msg)
                response_id = extract_response_id(msg)
                break

        # 保存助手消息
        assistant_meta: dict[str, Any] | None = None
        if response_id:
            assistant_meta = {"response_id": response_id}
        assistant_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content=answer,
            meta=assistant_meta,
        )
        self._db.add(assistant_msg)

        stage_summaries = result.get("stage_summaries") or {}
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}
        external_evidence = extract_external_evidence_from_messages(messages)
        answer = append_compact_citations_to_answer(answer, external_evidence)
        await self._persist_external_evidence(run.id, external_evidence)

        # 更新运行状态
        run.status = AgentRunStatus.SUCCEEDED
        run.finished_at = now
        run.final_output = answer
        run.stage_summaries = stage_summaries
        context_metrics = self._build_context_metrics(messages)
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        run.metrics = {
            "latency_ms": int((now - started_at).total_seconds() * 1000),
            "context": context_metrics,
            **(replay_metrics or {}),
            **metrics,
        }

        await self._db.commit()
        await self._db.refresh(assistant_msg)
        await self._db.refresh(run)

        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=external_evidence,
            stage_summaries=run.stage_summaries
            if isinstance(run.stage_summaries, dict)
            else None,
            metrics=run.metrics if isinstance(run.metrics, dict) else None,
            run=AgentRunRead.model_validate(run),
        )
