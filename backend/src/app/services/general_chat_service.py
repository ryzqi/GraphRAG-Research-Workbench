"""全能代理服务。

使用 LangGraph 图实现，支持检查点持久化和 Human-in-the-loop。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.general_chat_graph import GeneralChatGraph, GeneralChatState
from app.core.checkpoint import CheckpointManager
from app.core.settings import get_settings
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_client import MCPClient
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.models.tool_invocation import InvocationStatus, ToolInvocation
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
)


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

    async def _load_history(
        self, session_id: uuid.UUID, limit: int
    ) -> list[LLMMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()
        return [
            LLMMessage(role=msg.role.value, content=msg.content)
            for msg in messages
        ]

    async def answer(
        self,
        *,
        session: ChatSession,
        user_content: str,
    ) -> ChatAnswerResponse:
        """处理用户问题并生成答案（使用 LangGraph）。"""
        started_at = datetime.now(timezone.utc)
        history = await self._load_history(session.id, limit=6)

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

        try:
            # 获取启用的扩展
            extensions: list[ToolExtension] = []
            if session.allow_external and self._settings.mcp_enabled:
                stmt = select(ToolExtension).where(
                    ToolExtension.status == ExtensionStatus.ENABLED
                )
                result = await self._db.execute(stmt)
                extensions = list(result.scalars().all())

            # 创建 LangGraph 图
            graph = GeneralChatGraph(
                llm=self._llm,
                mcp=self._mcp,
                extensions=extensions,
                require_confirmation=self._settings.mcp_confirmation_required,
            )

            # 使用 session_id 作为 thread_id 执行
            state = GeneralChatState(
                question=user_content,
                allow_external=session.allow_external and self._settings.mcp_enabled,
                history=history,
            )
            result = await graph.run(
                state,
                thread_id=str(session.id),
                checkpointer=CheckpointManager.get_checkpointer(),
            )

            # 保存工具调用记录
            for tool_result in result.tool_results:
                invocation = ToolInvocation(
                    run_id=run.id,
                    tool_name=tool_result["tool_name"],
                    purpose=f"回答问题: {user_content[:100]}",
                    requires_confirmation=self._settings.mcp_confirmation_required,
                    status=(
                        InvocationStatus.SUCCEEDED
                        if tool_result["success"]
                        else InvocationStatus.FAILED
                    ),
                    output={"result": tool_result["output"]} if tool_result["success"] else None,
                    error_message=tool_result["output"] if not tool_result["success"] else None,
                    finished_at=datetime.now(timezone.utc),
                )
                self._db.add(invocation)

            # 保存助手消息
            assistant_msg = ChatMessage(
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content=result.answer,
            )
            self._db.add(assistant_msg)

            # 更新运行状态
            run.status = AgentRunStatus.SUCCEEDED
            run.finished_at = datetime.now(timezone.utc)
            run.final_output = result.answer
            run.stage_summaries = result.stage_summaries
            run.metrics = {
                "extension_calls": len(result.tool_results),
                "latency_ms": int(
                    (run.finished_at - started_at).total_seconds() * 1000
                ),
            }

            await self._db.commit()
            await self._db.refresh(assistant_msg)
            await self._db.refresh(run)

            return ChatAnswerResponse(
                assistant_message=ChatMessageRead.model_validate(assistant_msg),
                evidence=[],
                run=AgentRunRead.model_validate(run),
            )

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()
            raise
