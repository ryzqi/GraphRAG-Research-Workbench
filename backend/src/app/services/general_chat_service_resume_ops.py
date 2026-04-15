from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.agents.general_chat_agent import build_general_chat_agent, build_hitl_interrupt_on
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.integrations.chat_model_factory import create_chat_model
from app.models.agent_run import AgentRun
from app.models.chat_session import ChatSession
from app.schemas.chats import (
    AgentRunRead,
    ChatPendingToolApprovalResponse,
    PendingInterruptApproval,
    PendingToolCall,
    ToolApprovalRequest,
)
from app.services.general_chat_service_interrupts import _extract_pending_interrupts


async def resume_after_tool_approval(
    self,
    *,
    session: ChatSession,
    run: AgentRun,
    approval: ToolApprovalRequest,
):
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

        (
            tools,
            tool_meta_by_name,
        ) = await self._open_runtime_tool_registry_for_session(session=session)
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
        config = cast(RunnableConfig, CheckpointManager.make_config(thread_id))
        result = await agent.ainvoke(Command(resume=resume_payload), config)

        if not isinstance(result, dict):
            raise RuntimeError("LangGraph 返回类型不符合预期")

        interrupts = result.get("__interrupt__")
        if isinstance(interrupts, list) and interrupts:
            next_pending_interrupts = self._build_pending_interrupt_approvals(
                interrupts,
                tool_meta_by_name,
            )
            result_messages = result.get("messages")
            context_metrics = self._build_context_metrics(
                result_messages if isinstance(result_messages, list) else []
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
