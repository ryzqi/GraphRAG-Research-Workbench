from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, cast

from langchain.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from app.agents.general_chat_agent import build_general_chat_agent, build_hitl_interrupt_on
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_request_dedup import ChatRequestDedup
from app.models.chat_session import ChatSession
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    ChatPendingToolApprovalResponse,
    PendingInterruptApproval,
    PendingToolCall,
)
from app.search.web.citations import (
    append_compact_citations_to_answer,
    extract_external_evidence_from_messages,
)
from app.services.chat_replay_policy import ReplayDecision, ReplayMode
from app.services.general_chat_service_contracts import _as_str_dict
from app.services.general_chat_service_resume_ops import resume_after_tool_approval
from app.services.general_chat_service_streaming_ops import (
    answer_stream,
    resume_after_tool_approval_stream,
)
from app.services.message_normalizer import checkpoint_messages_require_reset, extract_response_id
from app.services.streaming import (
    extract_answer_text,
    extract_message_text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "answer",
    "answer_stream",
    "resume_after_tool_approval",
    "resume_after_tool_approval_stream",
]


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
        select(ChatSession.id).where(ChatSession.id == session_id).with_for_update()
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
        select(ChatSession.id).where(ChatSession.id == session.id).with_for_update()
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
    stage_summaries = (
        run.stage_summaries if isinstance(run.stage_summaries, dict) else {}
    )
    tool_approval = _as_str_dict(stage_summaries.get("tool_approval"))
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
    message = _extract_upstream_error_message(exc).lower()
    return "response with id" in message and "not found" in message


@staticmethod
def _should_recover_from_response_not_found(
    exc: Exception,
    replay_decision: ReplayDecision,
) -> bool:
    return (
        replay_decision.allow_recovery
        and _is_previous_response_not_found_error(exc)
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


async def answer(
    self,
    *,
    session: ChatSession,
    user_content: str,
    client_request_id: str | None = None,
) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
    """处理用户问题并生成答案（使用 create_agent）。"""
    normalized_client_request_id = self._normalize_client_request_id(
        client_request_id
    )
    dedup_record: ChatRequestDedup | None = None
    if normalized_client_request_id:
        dedup_record, claimed = await self._claim_request_dedup(
            session_id=session.id,
            client_request_id=normalized_client_request_id,
        )
        if not claimed:
            if dedup_record is None:  # pragma: no cover - defensive
                raise RuntimeError("Missing dedup record for replay path")
            return await self._replay_dedup_request(
                session=session, dedup=dedup_record
            )

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
        checkpoint_values = (checkpoint_tuple.checkpoint or {}).get(
            "channel_values", {}
        )
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
    if (
        checkpoint_tuple is None
        or not isinstance(existing_messages, list)
        or not existing_messages
    ):
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
        (
            tools,
            tool_meta_by_name,
        ) = await self._open_runtime_tool_registry_for_session(session=session)
        hitl_interrupt_on = build_hitl_interrupt_on(tool_meta_by_name)

        # 构造初始 messages（历史 + 用户问题）
        system_prompt = self._prompts.render_with_few_shot("general_chat/system")
        first_history = self._sanitize_history_for_replay(
            original_history,
            require_assistant_response_id=require_assistant_response_id,
        )
        config = cast(RunnableConfig, CheckpointManager.make_config(thread_id))
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
                summary_keep_messages=self._settings.summary_keep_messages,
                summary_trim_tokens=self._settings.summary_trim_tokens,
                tool_context_trigger_tokens=self._settings.context_tool_max_tokens,
                tool_selector_enabled=self._settings.tool_selector_enabled,
                tool_selector_trigger_tool_count=self._settings.tool_selector_trigger_tool_count,
                tool_selector_max_tools=self._settings.tool_selector_max_tools,
                tool_selector_model_id=self._settings.tool_selector_model_id,
                tool_selector_use_previous_response_id=replay_decision.use_previous_response_id,
                tool_selector_model=None,
                tool_selector_always_include=self._settings.tool_selector_always_include,
                pii_middleware_enabled=self._settings.pii_middleware_enabled,
                pii_redaction_strategy=self._settings.pii_redaction_strategy,
                pii_apply_to_tool_results=self._settings.pii_apply_to_tool_results,
                hitl_interrupt_on=hitl_interrupt_on,
            )
            result = await agent.ainvoke(
                cast(Any, {"messages": messages}),
                config,
            )
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
                summary_keep_messages=self._settings.summary_keep_messages,
                summary_trim_tokens=self._settings.summary_trim_tokens,
                tool_context_trigger_tokens=self._settings.context_tool_max_tokens,
                tool_selector_enabled=self._settings.tool_selector_enabled,
                tool_selector_trigger_tool_count=self._settings.tool_selector_trigger_tool_count,
                tool_selector_max_tools=self._settings.tool_selector_max_tools,
                tool_selector_model_id=self._settings.tool_selector_model_id,
                tool_selector_use_previous_response_id=recovery_decision.use_previous_response_id,
                tool_selector_model=None,
                tool_selector_always_include=self._settings.tool_selector_always_include,
                pii_middleware_enabled=self._settings.pii_middleware_enabled,
                pii_redaction_strategy=self._settings.pii_redaction_strategy,
                pii_apply_to_tool_results=self._settings.pii_apply_to_tool_results,
                hitl_interrupt_on=hitl_interrupt_on,
            )
            result = await recovery_agent.ainvoke(
                cast(Any, {"messages": recovery_messages}),
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
            result_messages = result.get("messages")
            context_metrics = self._build_context_metrics(
                result_messages if isinstance(result_messages, list) else []
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
                    (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
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
