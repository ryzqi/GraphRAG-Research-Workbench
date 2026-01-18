"""全能代理服务。

使用 LangGraph 图实现，支持检查点持久化和 Human-in-the-loop。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.general_chat_graph import GeneralChatGraph, GeneralChatState
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tool_calling.utils import extract_tool_results
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.core.settings import get_settings
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_client import MCPClient
from app.prompts import get_prompt_loader
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.models.tool_invocation import InvocationStatus, ToolInvocation
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatPendingToolApprovalResponse,
    ChatMessageRead,
    PendingToolCall,
)
from app.services.context_builder import ContextBuilder
from app.services.conversation_summary_service import ConversationSummaryService

logger = logging.getLogger(__name__)


class GeneralChatService:
    """全能代理服务，支持 MCP 扩展调用和检查点持久化。"""

    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
        mcp: MCPClient,
    ) -> None:
        self._db = db
        self._llm = llm
        self._mcp = mcp
        self._settings = get_settings()
        self._context_builder = ContextBuilder(self._settings)
        self._summary_service = ConversationSummaryService(db, settings=self._settings)
        self._prompts = get_prompt_loader()

    async def _load_history(
        self, session_id: uuid.UUID, limit: int
    ) -> list[LLMMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit * 2)
        )
        result = await self._db.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()
        filtered = [m for m in messages if not self._summary_service.is_summary_message(m)]
        if len(filtered) > limit:
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

    async def answer(
        self,
        *,
        session: ChatSession,
        user_content: str,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        """处理用户问题并生成答案（使用 LangGraph）。"""
        started_at = datetime.now(timezone.utc)
        summary = await self._summary_service.load_latest_summary(session.id)
        history = await self._load_history(
            session.id, limit=self._settings.context_history_max_messages
        )

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
            extensions: list[ToolExtension] = []
            if session.allow_external and self._settings.mcp_enabled:
                stmt = select(ToolExtension).where(
                    ToolExtension.status == ExtensionStatus.ENABLED
                )
                result = await self._db.execute(stmt)
                extensions = list(result.scalars().all())

            include_external = bool(session.allow_external)

            # 统一工具注册（内置 + MCP）
            tools, tool_meta_by_name = await build_tool_registry(
                settings=self._settings,
                mcp=self._mcp,
                extensions=extensions,
                extra_tools=[],
                include_web_search=include_external,
                include_mcp=include_external,
            )

            # 绑定工具的模型（OpenAI-compatible base_url）
            chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url.rstrip("/"),
            )

            # 构造初始 messages（系统提示词 + 摘要/历史 + 用户问题）
            system_prompt = self._prompts.render("general_chat/system")
            history_messages, history_usage, history_truncation = (
                self._context_builder.build_history_messages(
                    history=history,
                    summary_text=summary.content if summary else None,
                )
            )
            context_metrics = self._context_builder.build_metrics(
                history_usage=history_usage,
                history_truncation=history_truncation,
            )
            messages = [
                SystemMessage(content=system_prompt),
                *[self._to_langchain_message(m) for m in history_messages],
                HumanMessage(content=user_content),
            ]

            # 创建 LangGraph 图
            graph = GeneralChatGraph(
                chat_model=chat_model,
                tools=tools,
                tool_meta_by_name=tool_meta_by_name,
                require_confirmation=bool(
                    include_external and self._settings.mcp_confirmation_required
                ),
            )

            # 使用 session_id 作为 thread_id 执行
            state: GeneralChatState = {
                "messages": messages,
                "pending_tool_calls": [],
                "stage_summaries": {},
                "metrics": {"context": context_metrics},
                "human_approved": None,
            }
            thread_id = str(session.id)
            result = await graph.run(
                state,
                thread_id=thread_id,
                checkpointer=CheckpointManager.get_checkpointer(),
            )

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            interrupts = result.get("__interrupt__")
            if isinstance(interrupts, list) and interrupts:
                pending_tool_calls = result.get("pending_tool_calls")
                if not isinstance(pending_tool_calls, list):
                    pending_tool_calls = []

                interrupt_id = None
                message = None
                first = interrupts[0]
                interrupt_id = getattr(first, "id", None)
                payload = getattr(first, "value", None)
                if isinstance(payload, dict):
                    message = payload.get("message")
                    tools = payload.get("tools")
                    if isinstance(tools, list):
                        pending_tool_calls = tools

                stage_summaries = result.get("stage_summaries")
                if not isinstance(stage_summaries, dict):
                    stage_summaries = {}
                metrics = result.get("metrics")
                if not isinstance(metrics, dict):
                    metrics = {}

                run.stage_summaries = {
                    **stage_summaries,
                    "tool_approval": {
                        "pending": True,
                        "tool_count": len(pending_tool_calls),
                        "interrupt_id": interrupt_id,
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
                run.metrics = {
                    "extension_calls": 0,
                    "latency_ms": int(
                        (datetime.now(timezone.utc) - started_at).total_seconds()
                        * 1000
                    ),
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
                user_content=user_content,
                started_at=started_at,
                result=result,
                tool_meta_by_name=tool_meta_by_name,
                user_confirmed=None,
            )

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()
            raise
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

        pending_interrupts = [
            item for item in (checkpoint_tuple.pending_writes or []) if item[1] == "__interrupt__"
        ]
        if not pending_interrupts:
            set_run_id(None)
            raise AppError(
                code="NO_PENDING_APPROVAL",
                message="当前会话没有待审批的工具调用",
                status_code=400,
            )

        # 兜底：确保相关扩展已连接（避免服务重启导致内存连接丢失）
        pending_tool_calls = (
            (checkpoint_tuple.checkpoint or {})
            .get("channel_values", {})
            .get("pending_tool_calls", [])
        )
        if not isinstance(pending_tool_calls, list):
            pending_tool_calls = []
        await self._ensure_extensions_connected(pending_tool_calls)

        # 为恢复执行重新构建图（状态由 checkpointer 提供）
        extensions: list[ToolExtension] = []
        if session.allow_external and self._settings.mcp_enabled:
            stmt = select(ToolExtension).where(
                ToolExtension.status == ExtensionStatus.ENABLED
            )
            ext_result = await self._db.execute(stmt)
            extensions = list(ext_result.scalars().all())

        include_external = bool(session.allow_external)

        tools, tool_meta_by_name = await build_tool_registry(
            settings=self._settings,
            mcp=self._mcp,
            extensions=extensions,
            extra_tools=[],
            include_web_search=include_external,
            include_mcp=include_external,
        )

        chat_model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
        )

        graph = GeneralChatGraph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            require_confirmation=bool(
                include_external and self._settings.mcp_confirmation_required
            ),
        )
        compiled = graph.compile(checkpointer=CheckpointManager.get_checkpointer())
        config = CheckpointManager.make_config(thread_id)
        result = await compiled.ainvoke(Command(resume={"approved": approved}), config)

        if not isinstance(result, dict):
            set_run_id(None)
            raise RuntimeError("LangGraph 返回类型不符合预期")

        interrupts = result.get("__interrupt__")
        if isinstance(interrupts, list) and interrupts:
            pending_tool_calls = result.get("pending_tool_calls")
            if not isinstance(pending_tool_calls, list):
                pending_tool_calls = []
            first = interrupts[0]
            interrupt_id = getattr(first, "id", None)
            payload = getattr(first, "value", None)
            message = payload.get("message") if isinstance(payload, dict) else None
            tools = payload.get("tools") if isinstance(payload, dict) else None
            if isinstance(tools, list):
                pending_tool_calls = tools

            stage_summaries = result.get("stage_summaries")
            if not isinstance(stage_summaries, dict):
                stage_summaries = {}

            run.stage_summaries = {
                **stage_summaries,
                "tool_approval": {
                    "pending": True,
                    "tool_count": len(pending_tool_calls),
                    "interrupt_id": interrupt_id,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                },
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
                user_content=run.question,
                started_at=started_at,
                result=result,
                tool_meta_by_name=tool_meta_by_name,
                user_confirmed=approved,
            )
        finally:
            set_run_id(None)

    async def _ensure_extensions_connected(self, pending_tool_calls: object) -> None:
        if (
            not self._settings.mcp_enabled
            or not isinstance(pending_tool_calls, list)
            or not pending_tool_calls
        ):
            return

        extension_ids: set[uuid.UUID] = set()
        for item in pending_tool_calls:
            if not isinstance(item, dict):
                continue
            if item.get("is_builtin"):
                continue
            raw = item.get("extension_id")
            if not raw or raw == "builtin":
                continue
            try:
                extension_ids.add(uuid.UUID(str(raw)))
            except ValueError:
                continue

        if not extension_ids:
            return

        stmt = select(ToolExtension).where(ToolExtension.id.in_(extension_ids))
        result = await self._db.execute(stmt)
        extensions = list(result.scalars().all())
        for ext in extensions:
            await self._mcp.connect(
                str(ext.id), ext.transport.value, ext.endpoint, ext.scope
            )

    async def _finalize_run(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        user_content: str,
        started_at: datetime,
        result: dict,
        tool_meta_by_name: dict[str, Any],
        user_confirmed: bool | None,
    ) -> ChatAnswerResponse:
        messages = result.get("messages") or []
        if not isinstance(messages, list):
            messages = []

        tool_results = extract_tool_results(messages, tool_meta_by_name)

        # approved=false 时：不执行任何外部工具，且不写入 MCP 工具审计记录（需求：0 或 canceled）。
        audit_tool_results = tool_results
        if user_confirmed is False and self._settings.mcp_confirmation_required:
            audit_tool_results = []

        # 保存工具调用记录（仅记录 MCP 扩展；内置工具没有 extension_id 外键）
        purpose = f"回答问题: {user_content[:100]}"
        now = datetime.now(timezone.utc)
        for tool_result in audit_tool_results:
            if tool_result.get("is_builtin"):
                continue
            raw_extension_id = tool_result.get("extension_id")
            if not raw_extension_id:
                continue
            try:
                extension_id = uuid.UUID(str(raw_extension_id))
            except ValueError:
                continue

            success = bool(tool_result.get("success"))
            output = tool_result.get("output")
            invocation = ToolInvocation(
                extension_id=extension_id,
                run_id=run.id,
                tool_name=str(tool_result.get("tool_name") or ""),
                purpose=purpose,
                input=tool_result.get("args")
                if isinstance(tool_result.get("args"), dict)
                else None,
                requires_confirmation=self._settings.mcp_confirmation_required,
                user_confirmed=user_confirmed
                if self._settings.mcp_confirmation_required
                else None,
                status=InvocationStatus.SUCCEEDED if success else InvocationStatus.FAILED,
                output={"result": output} if success else None,
                error_message=str(output) if not success and output is not None else None,
                finished_at=now,
            )
            self._db.add(invocation)

        answer = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                answer = str(msg.content or "")
                break

        # 保存助手消息
        assistant_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content=answer,
        )
        self._db.add(assistant_msg)

        summary_metrics: dict[str, object] = {}
        try:
            summary_result = await self._summary_service.maybe_update_summary(session.id)
            if summary_result:
                summary_metrics = {
                    "summary_updated": True,
                    "summary_message_id": str(summary_result.message.id),
                    **summary_result.stats,
                }
        except Exception as exc:  # pragma: no cover
            logger.warning("摘要更新失败: %s", exc)

        invocation_summaries: list[dict] = []
        for tr in audit_tool_results:
            invocation_summaries.append(
                {
                    "tool_name": tr.get("tool_name"),
                    "purpose": purpose,
                    "status": "succeeded" if tr.get("success") else "failed",
                    "extension_name": tr.get("extension_name"),
                }
            )

        stage_summaries = result.get("stage_summaries") or {}
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}
        stage_summaries = {
            **stage_summaries,
            "extensions": {"invocations": invocation_summaries},
        }

        # 更新运行状态
        run.status = AgentRunStatus.SUCCEEDED
        run.finished_at = now
        run.final_output = answer
        run.stage_summaries = stage_summaries
        run.metrics = {
            "extension_calls": len(audit_tool_results),
            "latency_ms": int((now - started_at).total_seconds() * 1000),
            **summary_metrics,
            **(result.get("metrics") or {}),
        }

        await self._db.commit()
        await self._db.refresh(assistant_msg)
        await self._db.refresh(run)

        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=[],
            run=AgentRunRead.model_validate(run),
        )
