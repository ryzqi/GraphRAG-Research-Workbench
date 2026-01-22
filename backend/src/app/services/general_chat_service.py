"""普通代理服务。

使用 LangChain create_agent + LangGraph checkpointer，实现中间件与 Human-in-the-loop。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.general_chat_agent import (
    SUMMARY_KEEP,
    SUMMARY_TRIGGER,
    build_general_chat_agent,
    build_hitl_decisions,
    build_pending_tool_calls,
)
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.system_time import build_system_time_tool
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.core.settings import get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.prompts import get_prompt_loader
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatPendingToolApprovalResponse,
    ChatMessageRead,
    PendingToolCall,
)
from app.services.context_builder import ContextBuilder
from app.services.streaming import (
    LegacyThinkParser,
    StreamState,
    apply_updates_chunk,
    extract_answer_text,
    extract_stream_delta,
)
from app.utils.token_counter import count_tokens_approximately

logger = logging.getLogger(__name__)

SUMMARY_META_FLAG = "summary"


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


def _extract_action_requests(interrupts: list[object]) -> list[dict[str, Any]]:
    action_requests: list[dict[str, Any]] = []
    for interrupt in interrupts:
        payload = interrupt if isinstance(interrupt, dict) else getattr(interrupt, "value", None)
        if not isinstance(payload, dict):
            continue
        items = payload.get("action_requests")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    action_requests.append(item)
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
        if channel == "__interrupt__" and value is not None:
            interrupts.append(value)
    return interrupts


class GeneralChatService:
    """普通代理服务，支持 MCP 扩展调用和检查点持久化。"""

    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
    ) -> None:
        self._db = db
        self._llm = llm
        self._settings = get_settings()
        self._context_builder = ContextBuilder(self._settings)
        self._prompts = get_prompt_loader()

    async def _load_history(
        self, session_id: uuid.UUID, limit: int | None
    ) -> list[LLMMessage]:
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
        return [
            LLMMessage(role=msg.role.value, content=msg.content)
            for msg in filtered
        ]

    @staticmethod
    def _to_langchain_message(msg: LLMMessage) -> SystemMessage | HumanMessage | AIMessage:
        role = (msg.role or "").lower()
        if role == "system":
            return SystemMessage(content=msg.content)
        if role == "assistant":
            return AIMessage(content=msg.content)
        return HumanMessage(content=msg.content)

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

        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

        if isinstance(status_code, int):
            if status_code in {401, 403}:
                return AppError(
                    code="LLM_AUTH_ERROR",
                    message="大模型服务鉴权失败，请检查 LLM_API_KEY / LLM_BASE_URL",
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
        history: list[LLMMessage], user_content: str
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        messages = [GeneralChatService._to_langchain_message(m) for m in history]
        messages.append(HumanMessage(content=user_content))
        return messages

    @staticmethod
    def _message_text_for_metrics(message: object) -> str:
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

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
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        """处理用户问题并生成答案（使用 create_agent）。"""
        started_at = datetime.now(timezone.utc)
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        history: list[LLMMessage] = []
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages")
        if checkpoint_tuple is None or not isinstance(existing_messages, list) or not existing_messages:
            history = await self._load_history(session.id, limit=None)

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
        await self._db.flush()
        await self._db.commit()
        set_run_id(str(run.id))

        try:
            # 获取启用的扩展
            include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
            include_web_search = bool(self._settings.web_search_api_key)
            extensions: list[ToolExtension] = []
            if include_mcp:
                stmt = select(ToolExtension).where(
                    ToolExtension.status == ExtensionStatus.ENABLED
                )
                result = await self._db.execute(stmt)
                extensions = list(result.scalars().all())

            # 统一工具注册（内置 + MCP）
            tools, tool_meta_by_name = await build_tool_registry(
                settings=self._settings,
                extensions=extensions,
                extra_tools=[build_system_time_tool()],
                include_web_search=include_web_search,
                include_mcp=include_mcp,
            )

            # 绑定工具的模型（OpenAI-compatible base_url）
            chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url.rstrip("/"),
                profile=build_chat_model_profile(self._settings),
            )

            # 构造初始 messages（历史 + 用户问题）
            system_prompt = self._prompts.render("general_chat/system")
            messages = self._build_agent_messages(history, user_content)

            # 创建普通代理（create_agent + middleware）
            agent = build_general_chat_agent(
                chat_model=chat_model,
                tools=tools,
                tool_meta_by_name=tool_meta_by_name,
                require_confirmation=bool(
                    include_mcp and self._settings.mcp_confirmation_required
                ),
                system_prompt=system_prompt,
                summary_trigger=self._build_summary_trigger(),
            )

            # 使用 thread_id 执行
            config = CheckpointManager.make_config(thread_id)
            result = await agent.ainvoke({"messages": messages}, config)

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            interrupts = result.get("__interrupt__")
            if isinstance(interrupts, list) and interrupts:
                action_requests = _extract_action_requests(interrupts)
                pending_tool_calls = build_pending_tool_calls(
                    action_requests, tool_meta_by_name
                )
                first = interrupts[0]
                interrupt_id = getattr(first, "id", None)
                payload = getattr(first, "value", None)
                message = _extract_interrupt_message(payload)
                context_metrics = self._build_context_metrics(
                    result.get("messages") if isinstance(result.get("messages"), list) else []
                )

                run.stage_summaries = {
                    "tool_approval": {
                        "pending": True,
                        "tool_count": len(pending_tool_calls),
                        "interrupt_id": interrupt_id,
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    },
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
                    **metrics,
                }

                await self._db.commit()
                await self._db.refresh(run)

                return ChatPendingToolApprovalResponse(
                    thread_id=thread_id,
                    interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
                    message=str(message) if message is not None else None,
                    pending_tool_calls=[
                        PendingToolCall.model_validate(item)
                        for item in pending_tool_calls
                        if isinstance(item, dict)
                    ],
                    run=AgentRunRead.model_validate(run),
                )

            return await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                result=result,
            )

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()

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
            set_run_id(None)

    async def answer_stream(
        self,
        *,
        session: ChatSession,
        user_content: str,
        request: object | None = None,
    ) -> Any:
        """处理用户问题并生成答案（流式 SSE）。"""
        started_at = datetime.now(timezone.utc)
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        history: list[LLMMessage] = []
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages")
        if checkpoint_tuple is None or not isinstance(existing_messages, list) or not existing_messages:
            history = await self._load_history(session.id, limit=None)

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
        await self._db.flush()
        await self._db.commit()
        set_run_id(str(run.id))

        try:
            # 获取启用的扩展
            include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
            include_web_search = bool(self._settings.web_search_api_key)
            extensions: list[ToolExtension] = []
            if include_mcp:
                stmt = select(ToolExtension).where(
                    ToolExtension.status == ExtensionStatus.ENABLED
                )
                result = await self._db.execute(stmt)
                extensions = list(result.scalars().all())

            # 统一工具注册（内置 + MCP）
            tools, tool_meta_by_name = await build_tool_registry(
                settings=self._settings,
                extensions=extensions,
                extra_tools=[build_system_time_tool()],
                include_web_search=include_web_search,
                include_mcp=include_mcp,
            )

            # 绑定工具的模型（OpenAI-compatible base_url）
            chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url.rstrip("/"),
                profile=build_chat_model_profile(self._settings),
            )

            # 构造初始 messages（历史 + 用户问题）
            system_prompt = self._prompts.render("general_chat/system")
            messages = self._build_agent_messages(history, user_content)

            # 创建普通代理（create_agent + middleware）
            agent = build_general_chat_agent(
                chat_model=chat_model,
                tools=tools,
                tool_meta_by_name=tool_meta_by_name,
                require_confirmation=bool(
                    include_mcp and self._settings.mcp_confirmation_required
                ),
                system_prompt=system_prompt,
                summary_trigger=self._build_summary_trigger(),
            )

            # 使用 thread_id 执行
            config = CheckpointManager.make_config(thread_id)

            # SSE: meta
            yield "meta", {
                "run_id": str(run.id),
                "session_id": str(session.id),
                "session_type": session.session_type.value,
                "thread_id": thread_id,
                "mode": session.mode.value,
            }

            existing_messages = []
            if checkpoint_tuple is not None:
                checkpoint_values = (checkpoint_tuple.checkpoint or {}).get(
                    "channel_values", {}
                )
                stored_messages = checkpoint_values.get("messages")
                if isinstance(stored_messages, list):
                    existing_messages = list(stored_messages)

            stream_state = StreamState(
                messages=[*existing_messages, *list(messages)],
                pending_tool_calls=[],
                stage_summaries={},
                metrics={},
            )
            legacy_think_parser = LegacyThinkParser()

            async for mode, chunk in agent.astream(
                {"messages": messages},
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
                        legacy_think_parser=legacy_think_parser,
                    )
                    for delta in deltas:
                        yield "delta", delta.to_dict()
                    continue

                if mode == "updates" and isinstance(chunk, dict):
                    interrupts = apply_updates_chunk(stream_state, chunk)
                    if interrupts:
                        action_requests = _extract_action_requests(interrupts)
                        pending_tool_calls = build_pending_tool_calls(
                            action_requests, tool_meta_by_name
                        )
                        first = interrupts[0]
                        interrupt_id = getattr(first, "id", None)
                        payload = getattr(first, "value", None)
                        message = _extract_interrupt_message(payload)
                        context_metrics = self._build_context_metrics(
                            stream_state.messages
                        )

                        run.stage_summaries = {
                            "tool_approval": {
                                "pending": True,
                                "tool_count": len(pending_tool_calls),
                                "interrupt_id": interrupt_id,
                                "requested_at": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                        run.metrics = {
                            "latency_ms": int(
                                (datetime.now(timezone.utc) - started_at).total_seconds()
                                * 1000
                            ),
                            "context": context_metrics,
                            **(stream_state.metrics if isinstance(stream_state.metrics, dict) else {}),
                        }

                        await self._db.commit()
                        await self._db.refresh(run)

                        response = ChatPendingToolApprovalResponse(
                            thread_id=thread_id,
                            interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
                            message=str(message) if message is not None else None,
                            pending_tool_calls=[
                                PendingToolCall.model_validate(item)
                                for item in pending_tool_calls
                                if isinstance(item, dict)
                            ],
                            run=AgentRunRead.model_validate(run),
                        )
                        yield "interrupt", response.model_dump(mode="json")
                        return

            for delta in legacy_think_parser.flush():
                yield "delta", delta.to_dict()

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
            )
            yield "final", final_response.model_dump(mode="json")

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()

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
            set_run_id(None)

    async def resume_after_tool_approval(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        approved: bool,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        """两阶段交互第 2 阶段：提交审批结果并恢复执行。"""
        set_run_id(str(run.id))
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        if checkpoint_tuple is None:
            set_run_id(None)
            raise AppError(
                code="CHECKPOINT_NOT_FOUND",
                message="检查点不存在，无法恢复执行",
                status_code=404,
            )

        pending_interrupts = _extract_pending_interrupts(
            checkpoint_tuple.pending_writes
        )
        if not pending_interrupts:
            set_run_id(None)
            raise AppError(
                code="NO_PENDING_APPROVAL",
                message="当前会话没有待审批的工具调用",
                status_code=400,
            )

        # 为恢复执行重新构建 agent（状态由 checkpointer 提供）
        include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
        include_web_search = bool(self._settings.web_search_api_key)
        extensions: list[ToolExtension] = []
        if include_mcp:
            stmt = select(ToolExtension).where(
                ToolExtension.status == ExtensionStatus.ENABLED
            )
            ext_result = await self._db.execute(stmt)
            extensions = list(ext_result.scalars().all())

        tools, tool_meta_by_name = await build_tool_registry(
            settings=self._settings,
            extensions=extensions,
            extra_tools=[build_system_time_tool()],
            include_web_search=include_web_search,
            include_mcp=include_mcp,
        )

        action_requests = _extract_action_requests(pending_interrupts)
        pending_tool_calls = build_pending_tool_calls(
            action_requests, tool_meta_by_name
        )
        await self._ensure_extensions_connected(pending_tool_calls)

        chat_model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
            profile=build_chat_model_profile(self._settings),
        )

        system_prompt = self._prompts.render("general_chat/system")
        agent = build_general_chat_agent(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            require_confirmation=bool(
                include_mcp and self._settings.mcp_confirmation_required
            ),
            system_prompt=system_prompt,
            summary_trigger=self._build_summary_trigger(),
        )
        config = CheckpointManager.make_config(thread_id)
        decisions = build_hitl_decisions(len(action_requests), approved)
        result = await agent.ainvoke(Command(resume={"decisions": decisions}), config)

        if not isinstance(result, dict):
            set_run_id(None)
            raise RuntimeError("LangGraph 返回类型不符合预期")

        interrupts = result.get("__interrupt__")
        if isinstance(interrupts, list) and interrupts:
            action_requests = _extract_action_requests(interrupts)
            pending_tool_calls = build_pending_tool_calls(
                action_requests, tool_meta_by_name
            )
            first = interrupts[0]
            interrupt_id = getattr(first, "id", None)
            payload = getattr(first, "value", None)
            message = _extract_interrupt_message(payload)
            context_metrics = self._build_context_metrics(
                result.get("messages") if isinstance(result.get("messages"), list) else []
            )

            run.stage_summaries = {
                "tool_approval": {
                    "pending": True,
                    "tool_count": len(pending_tool_calls),
                    "interrupt_id": interrupt_id,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            metrics = result.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}
            run.metrics = {
                **(run.metrics if isinstance(run.metrics, dict) else {}),
                "latency_ms": int(
                    (datetime.now(timezone.utc) - (run.started_at or datetime.now(timezone.utc))).total_seconds()
                    * 1000
                ),
                "context": context_metrics,
                **metrics,
            }
            await self._db.commit()
            await self._db.refresh(run)
            try:
                return ChatPendingToolApprovalResponse(
                    thread_id=thread_id,
                    interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
                    message=str(message) if message is not None else None,
                    pending_tool_calls=[
                        PendingToolCall.model_validate(item)
                        for item in pending_tool_calls
                        if isinstance(item, dict)
                    ],
                    run=AgentRunRead.model_validate(run),
                )
            finally:
                set_run_id(None)

        started_at = run.started_at or datetime.now(timezone.utc)
        try:
            return await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                result=result,
            )
        finally:
            set_run_id(None)

    async def resume_after_tool_approval_stream(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        approved: bool,
        request: object | None = None,
    ) -> Any:
        """两阶段交互第 2 阶段：提交审批结果并恢复执行（流式 SSE）。"""
        set_run_id(str(run.id))
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        if checkpoint_tuple is None:
            yield "error", {
                "code": "CHECKPOINT_NOT_FOUND",
                "message": "检查点不存在，无法恢复执行",
            }
            set_run_id(None)
            return

        pending_interrupts = _extract_pending_interrupts(
            checkpoint_tuple.pending_writes
        )
        if not pending_interrupts:
            yield "error", {
                "code": "NO_PENDING_APPROVAL",
                "message": "当前会话没有待审批的工具调用",
            }
            set_run_id(None)
            return

        # 为恢复执行重新构建 agent（状态由 checkpointer 提供）
        include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
        include_web_search = bool(self._settings.web_search_api_key)
        extensions: list[ToolExtension] = []
        if include_mcp:
            stmt = select(ToolExtension).where(
                ToolExtension.status == ExtensionStatus.ENABLED
            )
            ext_result = await self._db.execute(stmt)
            extensions = list(ext_result.scalars().all())

        tools, tool_meta_by_name = await build_tool_registry(
            settings=self._settings,
            extensions=extensions,
            extra_tools=[build_system_time_tool()],
            include_web_search=include_web_search,
            include_mcp=include_mcp,
        )

        action_requests = _extract_action_requests(pending_interrupts)
        pending_tool_calls = build_pending_tool_calls(
            action_requests, tool_meta_by_name
        )
        await self._ensure_extensions_connected(pending_tool_calls)

        chat_model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
            profile=build_chat_model_profile(self._settings),
        )

        system_prompt = self._prompts.render("general_chat/system")
        agent = build_general_chat_agent(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            require_confirmation=bool(
                include_mcp and self._settings.mcp_confirmation_required
            ),
            system_prompt=system_prompt,
            summary_trigger=self._build_summary_trigger(),
        )
        config = CheckpointManager.make_config(thread_id)
        decisions = build_hitl_decisions(len(action_requests), approved)

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

        try:
            legacy_think_parser = LegacyThinkParser()
            async for mode, chunk in agent.astream(
                Command(resume={"decisions": decisions}),
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
                        legacy_think_parser=legacy_think_parser,
                    )
                    for delta in deltas:
                        yield "delta", delta.to_dict()
                    continue

                if mode == "updates" and isinstance(chunk, dict):
                    interrupts = apply_updates_chunk(stream_state, chunk)
                    if interrupts:
                        action_requests = _extract_action_requests(interrupts)
                        pending_tool_calls = build_pending_tool_calls(
                            action_requests, tool_meta_by_name
                        )
                        first = interrupts[0]
                        interrupt_id = getattr(first, "id", None)
                        payload = getattr(first, "value", None)
                        message = _extract_interrupt_message(payload)
                        context_metrics = self._build_context_metrics(
                            stream_state.messages
                        )

                        run.stage_summaries = {
                            "tool_approval": {
                                "pending": True,
                                "tool_count": len(pending_tool_calls),
                                "interrupt_id": interrupt_id,
                                "requested_at": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                        run.metrics = {
                            **(run.metrics if isinstance(run.metrics, dict) else {}),
                            "latency_ms": int(
                                (datetime.now(timezone.utc) - (run.started_at or datetime.now(timezone.utc))).total_seconds()
                                * 1000
                            ),
                            "context": context_metrics,
                            **(stream_state.metrics if isinstance(stream_state.metrics, dict) else {}),
                        }
                        await self._db.commit()
                        await self._db.refresh(run)

                        response = ChatPendingToolApprovalResponse(
                            thread_id=thread_id,
                            interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
                            message=str(message) if message is not None else None,
                            pending_tool_calls=[
                                PendingToolCall.model_validate(item)
                                for item in pending_tool_calls
                                if isinstance(item, dict)
                            ],
                            run=AgentRunRead.model_validate(run),
                        )
                        yield "interrupt", response.model_dump(mode="json")
                        return

            for delta in legacy_think_parser.flush():
                yield "delta", delta.to_dict()

            started_at = run.started_at or datetime.now(timezone.utc)
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
            )
            yield "final", final_response.model_dump(mode="json")

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()

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
            set_run_id(None)

    async def _ensure_extensions_connected(self, pending_tool_calls: object) -> None:
        # MultiServerMCPClient 默认无状态，无需显式预连接。
        return

    async def _finalize_run(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        started_at: datetime,
        result: dict,
    ) -> ChatAnswerResponse:
        messages = result.get("messages") or []
        if not isinstance(messages, list):
            messages = []

        now = datetime.now(timezone.utc)
        answer = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                # 提取纯文本回答（剥离思考段）
                answer = extract_answer_text(msg.content)
                break

        # 保存助手消息
        assistant_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content=answer,
        )
        self._db.add(assistant_msg)

        stage_summaries = result.get("stage_summaries") or {}
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}

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
            **metrics,
        }

        await self._db.commit()
        await self._db.refresh(assistant_msg)
        await self._db.refresh(run)

        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=[],
            run=AgentRunRead.model_validate(run),
        )
