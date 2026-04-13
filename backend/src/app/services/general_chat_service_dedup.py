from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_request_dedup import ChatRequestDedup
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence, EvidenceSourceKind
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    ChatPendingToolApprovalResponse,
    EvidenceItem,
    EvidenceSourceKind as EvidenceItemSourceKind,
)
from app.services.general_chat_service_contracts import (
    DEDUP_ATTACH_TIMEOUT_SECONDS,
    DEDUP_POLL_INTERVAL_SECONDS,
    DEDUP_RUN_WAIT_TIMEOUT_SECONDS,
    DEDUP_TABLE_NAME,
    _EXTERNAL_EVIDENCE_META_KEY,
)

logger = logging.getLogger(__name__)


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
    deadline = datetime.now(timezone.utc).timestamp() + DEDUP_ATTACH_TIMEOUT_SECONDS
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
    # 先清理上一轮 flush/commit 失败留下的坏事务，再重新加载运行记录。
    await self._db.rollback()
    current = await self._db.get(AgentRun, run_id) if run_id is not None else None
    if current is None:
        logger.warning(
            "Skip failed run persistence because agent run row no longer exists",
            extra={
                "run_id": str(run_id or ""),
                "original_exc_type": type(error).__name__,
            },
        )
        return
    current.status = AgentRunStatus.FAILED
    current.finished_at = datetime.now(timezone.utc)
    current.error_message = str(error)
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
    next_user_created_at = (
        await self._db.execute(next_user_stmt)
    ).scalar_one_or_none()

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
def _serialize_external_evidence_locator(
    item: EvidenceItem,
) -> dict[str, Any] | None:
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
        source_kind=EvidenceItemSourceKind(row.source_kind.value),
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


async def _replay_dedup_request(
    self,
    *,
    session: ChatSession,
    dedup: ChatRequestDedup,
) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
    bound = (
        dedup
        if dedup.run_id is not None
        else await self._wait_for_dedup_binding(dedup=dedup)
    )
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
