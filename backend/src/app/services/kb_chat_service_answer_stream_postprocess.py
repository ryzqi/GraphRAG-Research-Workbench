from __future__ import annotations

from datetime import datetime, timezone

from langchain.messages import AIMessage

from app.models.agent_run import AgentRunStatus
from app.services.kb_chat_service_contracts import _KbChatExecution, _KbChatStreamRunState
from app.services.streaming import extract_answer_text
async def _postprocess_live_stream(
    self,
    *,
    session,
    exec_ctx: _KbChatExecution,
    run,
    stream_state,
    stream_run_state: _KbChatStreamRunState,
    sse_heartbeat_stats,
    protocol_emit_total: int,
    protocol_drift_total: int,
    protocol_salvage_total: int,
    node_io_snapshot_truncated_count: int,
    custom_event_unhandled_count: int,
    last_good_answer: str | None,
    last_good_answer_source: str | None,
    _emit_enveloped,
    _emit_state,
    _emit_ui_event,
):
    answer = ""
    for msg in reversed(stream_state.messages):
        if isinstance(msg, AIMessage):
            answer = extract_answer_text(msg.content)
            break

    protocol_metrics = self._build_protocol_metrics(
        protocol_emit_total=protocol_emit_total,
        protocol_required_field_drift_count=protocol_drift_total,
        protocol_salvage_count=protocol_salvage_total,
        node_io_snapshot_truncated_count=node_io_snapshot_truncated_count,
        custom_event_unhandled_count=custom_event_unhandled_count,
        heartbeat_stats=sse_heartbeat_stats,
    )
    stream_state.metrics = {
        **(
            stream_state.metrics
            if isinstance(stream_state.metrics, dict)
            else {}
        ),
        **protocol_metrics,
    }

    metrics, stage_summaries = self._build_observability(
        kb_chat_config=exec_ctx.kb_chat_config,
        history_usage=exec_ctx.history_usage,
        history_truncation=exec_ctx.history_truncation,
        retrieval_meta=exec_ctx.retrieval_meta,
        retrieval_results=exec_ctx.retrieval_results,
        base_metrics=stream_state.metrics,
        base_stage_summaries=stream_state.stage_summaries,
        stage_attempts=stream_run_state.stage_attempts,
    )
    metrics = self._apply_guardrail_metrics(
        metrics=metrics,
        stage_summaries=stage_summaries,
        kb_scope=exec_ctx.retrieval_meta.get("kb_scope")
        if isinstance(exec_ctx.retrieval_meta, dict)
        else None,
    )

    clarification_message, pending_clarification = (
        self._extract_clarification_pending(
            clarification_payload=stream_state.clarification_payload,
            answer=answer,
            reflection=stream_state.reflection,
        )
    )
    candidate, candidate_source = self._extract_last_good_answer(
        answer=answer,
        stream_state=stream_state,
    )
    if candidate:
        last_good_answer = candidate
        last_good_answer_source = candidate_source

    terminal_candidate = (
        "out202" if clarification_message is not None else "status"
    )
    yield _emit_enveloped(
        event_type="stream_end",
        payload={
            "run_id": str(run.id),
            "terminal_candidate": terminal_candidate,
            "answer_preview": answer[:200],
            "stage_summaries": stage_summaries,
            "metrics": metrics,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    if clarification_message is not None:
        max_rounds = max(
            0,
            int(getattr(self._settings, "kb_chat_max_clarification_rounds", 1)),
        )
        current_rounds = self._clarification_round_count(
            run.metrics if isinstance(run.metrics, dict) else None
        )
        if current_rounds < max_rounds:
            if last_good_answer:
                yield _emit_ui_event(
                    event_type="candidate_answer_updated",
                    candidate_answer=last_good_answer,
                    source_step_id=last_good_answer_source,
                )
            pending_response = await self._persist_clarification_pending(
                session=session,
                run=run,
                started_at=exec_ctx.started_at,
                message=clarification_message,
                pending_clarification=pending_clarification,
                stage_summaries=stage_summaries,
                metrics=metrics,
            )
            run_payload = pending_response.run.model_dump(mode="json")
            yield _emit_state(
                run_status="waiting_user",
                message=pending_response.message,
                current_step_status_override="waiting_user",
            )
            yield (
                "interrupt",
                self._build_terminal_event_payload(
                    status=pending_response.status,
                    run_payload=run_payload,
                    assistant_message=None,
                    evidence=[],
                    stage_summaries=(
                        pending_response.stage_summaries
                        if isinstance(pending_response.stage_summaries, dict)
                        else None
                    ),
                    metrics=(
                        pending_response.metrics
                        if isinstance(pending_response.metrics, dict)
                        else None
                    ),
                    message=pending_response.message,
                    pending_clarification=(
                        pending_response.pending_clarification.model_dump(
                            mode="json"
                        )
                        if pending_response.pending_clarification is not None
                        else None
                    ),
                    source=pending_response.source,
                    cache=(
                        pending_response.cache.model_dump(mode="json")
                        if pending_response.cache is not None
                        else None
                    ),
                ),
            )
            return
        stage_summaries = {
            **stage_summaries,
            "clarification_pending": {
                "pending": False,
                "round": current_rounds,
                "max_rounds": max_rounds,
                "max_rounds_reached": True,
                "message": clarification_message,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        answer = (
            "基于当前对话信息仍存在关键歧义，暂时无法给出可靠结论。"
            "请在下一次提问时明确对象、范围与时间。"
        )

    terminal_status, terminal_message = self._resolve_terminal_run_status(
        answer=answer,
        clarification_payload=stream_state.clarification_payload,
        routing_decisions=stream_state.routing_decisions,
        reflection=stream_state.reflection,
        best_answer=stream_state.best_answer,
    )
    if terminal_status == AgentRunStatus.FAILED and last_good_answer:
        yield _emit_ui_event(
            event_type="degraded_to_candidate",
            message="最终回答失败，已回退展示候选答案。",
            candidate_answer=last_good_answer,
            source_step_id=last_good_answer_source,
            degrade_reason_value=terminal_message,
        )

    final_response = await self._finalize_run(
        session=session,
        run=run,
        kb_chat_config=exec_ctx.kb_chat_config,
        started_at=exec_ctx.started_at,
        question_vector=exec_ctx.semantic_cache_question_vector,
        answer=answer,
        final_evidence_items=stream_state.evidence_items,
        final_citation_catalog=stream_state.citation_catalog,
        stage_summaries=stage_summaries,
        metrics=metrics,
        status=terminal_status,
        error_message=terminal_message,
        terminal_reason=self._resolve_terminal_reason(
            clarification_payload=stream_state.clarification_payload,
            routing_decisions=stream_state.routing_decisions,
            reflection=stream_state.reflection,
            degrade_reason=stream_state.degrade_reason,
        ),
        clarification_payload=stream_state.clarification_payload,
        reflection=stream_state.reflection,
        query_strategy=stream_state.query_strategy,
        routing_decisions=stream_state.routing_decisions,
    )
    run_payload = final_response.run.model_dump(mode="json")
    yield _emit_state(
        run_status=final_response.status,
        message=terminal_message,
        degrade_reason_value=terminal_message,
        current_step_status_override=final_response.status,
    )
    yield (
        "final",
        self._build_terminal_event_payload(
            status=final_response.status,
            run_payload=run_payload,
            assistant_message=final_response.assistant_message.model_dump(
                mode="json"
            ),
            evidence=[
                item.model_dump(mode="json") for item in final_response.evidence
            ],
            stage_summaries=(
                final_response.stage_summaries
                if isinstance(final_response.stage_summaries, dict)
                else None
            ),
            metrics=(
                final_response.metrics
                if isinstance(final_response.metrics, dict)
                else None
            ),
            source=final_response.source,
            cache=(
                final_response.cache.model_dump(mode="json")
                if final_response.cache is not None
                else None
            ),
        ),
    )
