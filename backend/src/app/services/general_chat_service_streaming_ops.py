from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, cast

from langchain.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.agents.general_chat_agent import build_general_chat_agent, build_hitl_interrupt_on
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.pii import sanitize_with_settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_request_dedup import ChatRequestDedup
from app.models.chat_session import ChatSession
from app.schemas.chats import (
    AgentRunRead,
    ChatPendingToolApprovalResponse,
    ToolApprovalRequest,
)
from app.services.general_chat_service_interrupts import _extract_pending_interrupts
from app.services.message_normalizer import checkpoint_messages_require_reset
from app.services.streaming import StreamState, apply_updates_chunk, extract_stream_delta

logger = logging.getLogger(__name__)


def _sanitize_stream_delta_dicts(
    *,
    deltas: list[Any],
    settings: Any,
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for delta in deltas:
        payload = delta.to_dict() if hasattr(delta, "to_dict") else delta
        sanitized_value = sanitize_with_settings(payload, settings=settings)
        if isinstance(sanitized_value, dict):
            sanitized.append(sanitized_value)
    return sanitized


async def answer_stream(
    self,
    *,
    session: ChatSession,
    user_content: str,
    request: object | None = None,
    client_request_id: str | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """处理用户问题并生成答案（流式 SSE）。"""
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
            try:
                replay = await self._replay_dedup_request(
                    session=session,
                    dedup=dedup_record,
                )
            except AppError as app_error:
                yield (
                    "error",
                    {
                        "code": app_error.code,
                        "message": app_error.message,
                        "details": app_error.details,
                    },
                )
                return
            yield (
                "meta",
                {
                    "run_id": str(replay.run.id),
                    "session_id": str(session.id),
                    "session_type": session.session_type.value,
                    "thread_id": str(session.id),
                    "mode": session.mode.value,
                    "dedup_hit": True,
                },
            )
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
        yield (
            "error",
            {
                "code": "MODEL_CONFIG_INCOMPLETE",
                "message": str(exc),
            },
        )
        return
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

    user_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.USER,
        content=user_content,
    )
    self._db.add(user_msg)

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
        (
            tools,
            tool_meta_by_name,
        ) = await self._open_runtime_tool_registry_for_session(session=session)
        hitl_interrupt_on = build_hitl_interrupt_on(tool_meta_by_name)

        system_prompt = self._prompts.render_with_few_shot("general_chat/system")
        config = cast(RunnableConfig, CheckpointManager.make_config(thread_id))
        replay_metrics = self._build_replay_metrics(replay_decision)

        yield (
            "meta",
            {
                "run_id": str(run.id),
                "session_id": str(session.id),
                "session_type": session.session_type.value,
                "thread_id": thread_id,
                "mode": session.mode.value,
            },
        )

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
            stream_state = StreamState(
                messages=[*attempt_checkpoint_messages, *list(attempt_messages)],
                pending_tool_calls=[],
                stage_summaries={},
                metrics={},
            )
            emitted_payload = False

            try:
                async for mode, chunk in agent.astream(
                    cast(Any, {"messages": attempt_messages}),
                    config,
                    stream_mode=["messages", "updates"],
                ):
                    if request is not None:
                        is_disconnected = getattr(request, "is_disconnected", None)
                        if callable(is_disconnected):
                            disconnect_checker = cast(
                                Callable[[], Awaitable[bool]],
                                is_disconnected,
                            )
                            if await disconnect_checker():
                                run.status = AgentRunStatus.CANCELED
                                run.finished_at = datetime.now(timezone.utc)
                                await self._db.commit()
                                return

                    if mode == "messages":
                        token, meta = chunk
                        deltas = extract_stream_delta(
                            token,
                            meta if isinstance(meta, dict) else None,
                        )
                        if deltas:
                            emitted_payload = True
                            node_name = (
                                meta.get("langgraph_node")
                                if isinstance(meta, dict)
                                and isinstance(meta.get("langgraph_node"), str)
                                else None
                            )
                            yield (
                                "messages",
                                {
                                    "run_id": str(run.id),
                                    "node": node_name,
                                    "deltas": _sanitize_stream_delta_dicts(
                                        deltas=deltas,
                                        settings=self._settings,
                                    ),
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                        continue

                    if mode == "updates" and isinstance(chunk, dict):
                        interrupts = apply_updates_chunk(stream_state, chunk)
                        if interrupts:
                            pending_interrupts = (
                                self._build_pending_interrupt_approvals(
                                    interrupts,
                                    tool_meta_by_name,
                                )
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
                                    (
                                        datetime.now(timezone.utc) - started_at
                                    ).total_seconds()
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
                    recovery_history = await self._load_history(
                        session.id, limit=None
                    )
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
            yield (
                "error",
                {
                    "code": "MODEL_CONFIG_INCOMPLETE",
                    "message": str(e),
                },
            )
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
            yield (
                "error",
                {
                    "code": mapped.code,
                    "message": mapped.message,
                    "details": mapped.details,
                },
            )
            return

        yield (
            "error",
            {
                "code": "CHAT_STREAM_FAILED",
                "message": str(e),
            },
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
) -> AsyncIterator[tuple[str, Any]]:
    """两阶段交互第 2 阶段：提交审批结果并恢复执行（流式 SSE）。"""
    set_run_id(str(run.id))
    try:
        await self._ensure_resume_target_valid(session=session, run=run)
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        if checkpoint_tuple is None:
            yield (
                "error",
                {
                    "code": "CHECKPOINT_NOT_FOUND",
                    "message": "检查点不存在，无法恢复执行",
                },
            )
            return

        pending_interrupts_raw = _extract_pending_interrupts(
            checkpoint_tuple.pending_writes
        )
        if not pending_interrupts_raw:
            yield (
                "error",
                {
                    "code": "NO_PENDING_APPROVAL",
                    "message": "当前会话没有待审批的工具调用",
                },
            )
            return

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
        config = cast(RunnableConfig, CheckpointManager.make_config(thread_id))

        checkpoint_values = (checkpoint_tuple.checkpoint or {}).get(
            "channel_values", {}
        )
        existing_messages = checkpoint_values.get("messages", [])
        stream_state = StreamState(
            messages=list(existing_messages)
            if isinstance(existing_messages, list)
            else [],
            pending_tool_calls=[],
            stage_summaries={},
            metrics={},
        )

        yield (
            "meta",
            {
                "run_id": str(run.id),
                "session_id": str(session.id),
                "session_type": session.session_type.value,
                "thread_id": thread_id,
                "mode": session.mode.value,
                "resumed": True,
            },
        )

        async for mode, chunk in agent.astream(
            Command(resume=resume_payload),
            config,
            stream_mode=["messages", "updates"],
        ):
            if request is not None:
                is_disconnected = getattr(request, "is_disconnected", None)
                if callable(is_disconnected):
                    disconnect_checker = cast(
                        Callable[[], Awaitable[bool]],
                        is_disconnected,
                    )
                    if await disconnect_checker():
                        run.status = AgentRunStatus.CANCELED
                        run.finished_at = datetime.now(timezone.utc)
                        await self._db.commit()
                        return

            if mode == "messages":
                token, meta = chunk
                deltas = extract_stream_delta(
                    token,
                    meta if isinstance(meta, dict) else None,
                )
                if deltas:
                    node_name = (
                        meta.get("langgraph_node")
                        if isinstance(meta, dict)
                        and isinstance(meta.get("langgraph_node"), str)
                        else None
                    )
                    yield (
                        "messages",
                        {
                            "run_id": str(run.id),
                            "node": node_name,
                            "deltas": _sanitize_stream_delta_dicts(
                                deltas=deltas,
                                settings=self._settings,
                            ),
                            "ts": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                continue

            if mode == "updates" and isinstance(chunk, dict):
                interrupts = apply_updates_chunk(stream_state, chunk)
                if interrupts:
                    next_pending_interrupts = (
                        self._build_pending_interrupt_approvals(
                            interrupts,
                            tool_meta_by_name,
                        )
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
                            (
                                datetime.now(timezone.utc)
                                - (run.started_at or datetime.now(timezone.utc))
                            ).total_seconds()
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
            yield (
                "error",
                {
                    "code": "MODEL_CONFIG_INCOMPLETE",
                    "message": str(e),
                },
            )
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
            yield (
                "error",
                {
                    "code": mapped.code,
                    "message": mapped.message,
                    "details": mapped.details,
                },
            )
            return

        yield (
            "error",
            {
                "code": "CHAT_STREAM_FAILED",
                "message": str(e),
            },
        )
    finally:
        await self._close_runtime_tool_registry()
        set_run_id(None)
