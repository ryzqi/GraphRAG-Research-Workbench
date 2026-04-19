from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.errors import bad_request
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchPlanSnapshot,
    ResearchSessionCreateRequest,
)
from app.services.research_finalizer import ResearchFinalizerResult
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_observability import (
    ensure_research_trace_id,
)

async def submit_clarification(
    service: Any,
    *,
    session: ResearchSession,
    answer: str,
) -> tuple[ResearchSession, ResearchPlannerResult]:
    if session.status != ResearchSessionStatus.CLARIFYING:
        raise bad_request(
            code="RESEARCH_CLARIFICATION_NOT_ALLOWED",
            message="仅 clarifying 状态允许提交澄清",
        )
    allow_clarify = service._should_allow_follow_up_clarification(
        session=session,
        answer=answer,
    )
    effective_question = service._build_effective_planning_question(
        session=session,
        answer=answer,
    )
    await service._persist_clarification_answer(session=session, answer=answer)
    await service._event_store.append(
        session=session,
        event_type="research.clarification.submitted",
        phase="planner",
        payload={"answer": answer, "effective_question": effective_question},
        trace_id=session.trace_id,
    )
    plan_result = await service._planner.build_plan(
        ResearchSessionCreateRequest(question=effective_question),
        allow_clarify=allow_clarify,
    )
    if plan_result.clarification_request is not None:
        await service._persist_clarification_request(
            session=session,
            clarification_request=plan_result.clarification_request,
        )
        session.transition_to(ResearchSessionStatus.CLARIFYING)
        return session, plan_result

    if plan_result.plan_snapshot is None:
        raise bad_request(
            code="RESEARCH_PLAN_SNAPSHOT_MISSING",
            message="研究计划快照缺失",
        )
    await service._persist_planned_session_artifacts(
        session=session,
        plan_result=plan_result,
    )
    await service._event_store.append(
        session=session,
        event_type="research.plan.ready",
        phase="planner",
        payload={
            **(
                plan_result.artifact_payload
                if isinstance(plan_result.artifact_payload, dict)
                else {}
            ),
            "lc_agent_name": "planner",
            "decision_source": "llm_scoper",
            "auto_start": False,
        },
        trace_id=session.trace_id,
    )
    session.transition_to(plan_result.next_status)
    service._ensure_dispatch_outbox(session=session)
    return session, plan_result

async def update_plan(
    service: Any,
    *,
    session: ResearchSession,
    feedback: str,
) -> tuple[ResearchSession, ResearchPlannerResult]:
    if session.status != ResearchSessionStatus.PLAN_READY:
        raise bad_request(
            code="RESEARCH_PLAN_UPDATE_NOT_ALLOWED",
            message="仅 plan_ready 状态允许更新计划",
        )
    normalized_feedback = feedback.strip()
    if not normalized_feedback:
        raise bad_request(
            code="RESEARCH_PLAN_UPDATE_FEEDBACK_MISSING",
            message="更新计划需要提供 feedback",
        )
    await service._artifact_store.upsert(
        session=session,
        artifact_key="plan_feedback",
        content_text=normalized_feedback,
    )
    await service._event_store.append(
        session=session,
        event_type="research.plan.update_requested",
        phase="planner",
        payload={"feedback": normalized_feedback, "lc_agent_name": "planner"},
        trace_id=session.trace_id,
    )
    effective_question = service._build_effective_planning_question(
        session=session,
        answer=normalized_feedback,
    )
    plan_result = await service._planner.build_plan(
        ResearchSessionCreateRequest(question=effective_question),
        allow_clarify=False,
    )
    if plan_result.clarification_request is not None:
        await service._persist_clarification_request(
            session=session,
            clarification_request=plan_result.clarification_request,
        )
        session.transition_to(ResearchSessionStatus.CLARIFYING)
        return session, plan_result

    if plan_result.plan_snapshot is None:
        raise bad_request(
            code="RESEARCH_PLAN_SNAPSHOT_MISSING",
            message="研究计划快照缺失",
        )
    await service._persist_planned_session_artifacts(
        session=session,
        plan_result=plan_result,
    )
    await service._event_store.append(
        session=session,
        event_type="research.plan.updated",
        phase="planner",
        payload={
            **(
                plan_result.artifact_payload
                if isinstance(plan_result.artifact_payload, dict)
                else {}
            ),
            "feedback": normalized_feedback,
            "lc_agent_name": "planner",
            "decision_source": "llm_scoper",
            "auto_start": False,
        },
        trace_id=session.trace_id,
    )
    session.transition_to(ResearchSessionStatus.PLAN_READY)
    return session, plan_result

async def start_session(service: Any, *, session: ResearchSession) -> ResearchSession:
    if session.status != ResearchSessionStatus.PLAN_READY:
        raise bad_request(
            code="RESEARCH_START_NOT_ALLOWED",
            message="仅 plan_ready 状态允许开始研究",
        )
    plan_snapshot = service.read_plan_snapshot(session)
    session.transition_to(ResearchSessionStatus.QUEUED)
    await service._event_store.append(
        session=session,
        event_type="research.run.queued",
        phase="planner",
        payload={"lc_agent_name": "planner"},
        trace_id=session.trace_id,
    )
    await service._persist_plan_progress_snapshot(
        session=session,
        plan_snapshot=plan_snapshot,
        phase="planner",
        current_step_index=1 if plan_snapshot.subtasks else None,
        completed_step_count=0,
    )
    await service._persist_runtime_execution_artifacts(
        session=session,
        plan_snapshot=plan_snapshot,
    )
    service._ensure_dispatch_outbox(session=session)
    return session

async def stop_session(
    service: Any,
    *,
    session: ResearchSession,
    reason: str | None = None,
) -> ResearchSession:
    normalized_reason = reason.strip() if isinstance(reason, str) else None
    runtime_stop = session.status in {
        ResearchSessionStatus.RUNNING,
        ResearchSessionStatus.FINALIZING,
    }
    if session.status in {
        ResearchSessionStatus.CREATED,
        ResearchSessionStatus.PLANNING,
        ResearchSessionStatus.CLARIFYING,
        ResearchSessionStatus.PLAN_READY,
        ResearchSessionStatus.QUEUED,
        ResearchSessionStatus.RUNNING,
        ResearchSessionStatus.FINALIZING,
    }:
        plan_snapshot = service._try_read_plan_snapshot(session)
        if plan_snapshot is not None:
            await service._persist_terminal_plan_progress_snapshot(
                session=session,
                plan_snapshot=plan_snapshot,
                phase="runtime" if runtime_stop else "planner",
                terminal_state="canceled",
            )
        session.transition_to(ResearchSessionStatus.CANCELED)
        await service._event_store.append(
            session=session,
            event_type="research.run.stopped",
            phase="runtime" if runtime_stop else "planner",
            payload={
                "reason": normalized_reason,
                "lc_agent_name": "deep-research" if runtime_stop else "planner",
            },
            trace_id=session.trace_id,
        )
        return session
    if session.status == ResearchSessionStatus.CANCELED:
        return session
    raise bad_request(
        code="RESEARCH_STOP_NOT_ALLOWED",
        message="当前状态不允许停止研究",
    )


async def execute_session(
    service: Any,
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
) -> ResearchFinalizerResult | None:
    from app.services import research_service as research_service_module

    ensure_research_trace_id(session)
    session.transition_to(ResearchSessionStatus.RUNNING)
    session.runtime_phase = "runtime"
    session.started_at = datetime.now(timezone.utc)
    await service._persist_runtime_start(
        session=session,
        plan_snapshot=plan_snapshot,
    )
    await service._commit_checkpoint()

    runtime_result = await service._runtime_runner.run_session(
        session=session,
        plan_snapshot=plan_snapshot,
        runtime_activity_callback=service._build_runtime_activity_callback(
            session=session,
            plan_snapshot=plan_snapshot,
        ),
    )
    source_bundle = runtime_result.source_bundle
    effective_runtime_context_snapshot = service._merge_runtime_projection_snapshot(
        session=session,
        runtime_context_snapshot=runtime_result.runtime_context_snapshot,
    )
    await service._persist_runtime_results(
        session=session,
        plan_snapshot=plan_snapshot,
        runtime_result=runtime_result,
        runtime_context_snapshot=effective_runtime_context_snapshot,
    )
    await service._commit_checkpoint()

    committed_status = await service._read_committed_session_status(session=session)
    if committed_status == ResearchSessionStatus.CANCELED:
        if session.status != ResearchSessionStatus.CANCELED:
            session.transition_to(ResearchSessionStatus.CANCELED)
        if session.finished_at is None:
            session.finished_at = datetime.now(timezone.utc)
        return None

    session.transition_to(ResearchSessionStatus.FINALIZING)
    session.finalizer_phase = "finalizer"
    await service._persist_finalizer_start(
        session=session,
        plan_snapshot=plan_snapshot,
        coverage_gaps=list(source_bundle.coverage_gaps),
    )
    await service._commit_checkpoint()

    final_result = await service._finalizer.finalize_async(
        question=session.question,
        target_sources=plan_snapshot.target_sources,
        source_bundle=source_bundle,
        runtime_context_snapshot=effective_runtime_context_snapshot,
    )
    metrics = research_service_module.build_research_metrics(
        session=session,
        plan_snapshot=plan_snapshot,
        runtime_result=runtime_result,
    )
    replay = research_service_module.evaluate_research_replay_consistency(
        session=session,
        events=service.list_event_envelopes(session),
    )
    metrics["replay"] = replay
    metrics["gate"] = research_service_module.evaluate_research_gate(
        metrics=metrics,
        thresholds=service._gate_thresholds,
    )
    session.transition_to(ResearchSessionStatus.FINAL)
    session.finished_at = datetime.now(timezone.utc)
    await service._persist_finalized_session(
        session=session,
        final_result=final_result,
        metrics=metrics,
    )
    await service._commit_checkpoint()
    return final_result

async def fail_session(
    service: Any,
    *,
    session: ResearchSession,
    exc: Exception,
    phase: str,
    source_provider: str | None = None,
) -> ResearchSession:
    from app.services import research_service as research_service_module

    ensure_research_trace_id(session)
    plan_snapshot = None
    if not session.status.is_terminal():
        plan_snapshot = service._try_read_plan_snapshot(session)
        session.transition_to(ResearchSessionStatus.FAILED)
    session.error_message = str(exc)
    session.finished_at = datetime.now(timezone.utc)
    fault = research_service_module.classify_research_fault(exc, source_provider=source_provider)
    metrics = research_service_module.build_failure_metrics(
        session=session,
        fault=fault,
        thresholds=service._gate_thresholds,
        existing_metrics=session.metrics
        if isinstance(session.metrics, dict)
        else None,
    )
    await service._persist_failed_session(
        session=session,
        exc=exc,
        phase=phase,
        source_provider=source_provider,
        fault=fault,
        metrics=metrics,
        plan_snapshot=plan_snapshot,
    )
    return session
