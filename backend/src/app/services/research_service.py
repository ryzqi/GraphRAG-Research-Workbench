"""Research session orchestration service。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.settings import Settings, get_settings
from app.core.errors import bad_request, not_found
from app.models.research_artifact import ResearchArtifact
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.models.research_task_outbox import (
    RESEARCH_SESSION_TASK_NAME,
    ResearchTaskOutbox,
    ResearchTaskOutboxStatus,
)
from app.schemas.research import (
    ResearchArtifactRead,
    ResearchArtifactsResponse,
    ResearchCanonicalCitation,
    ResearchClarificationRequest,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchSessionCreateRequest,
)
from app.services.research_artifact_store import ResearchArtifactStore
from app.services.research_event_store import ResearchEventStore
from app.services.research_finalizer import ResearchFinalizer, ResearchFinalizerResult
from app.services.research_observability import (
    ResearchRuntimeRunResult,
    build_failure_metrics,
    build_research_gate_thresholds,
    build_research_metrics,
    build_trace_links,
    classify_research_fault,
    ensure_research_trace_id,
    evaluate_research_gate,
)
from app.services.research_planner import ResearchPlanner
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_presentation_snapshot import (
    build_research_presentation_snapshot,
)
from app.services.research_replay import evaluate_research_replay_consistency
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_runtime_types import ResearchPlanProgressUpdate
from app.services.research_workspace_files import build_workspace_bootstrap_artifacts

PLAN_PROGRESS_ARTIFACT_KEY = "plan_progress_snapshot"
PLAN_PROGRESS_EVENT_TYPE = "research.plan_progress.updated"


class ResearchRuntimeRunner(Protocol):
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        plan_progress_callback=None,
    ) -> ResearchRuntimeRunResult: ...


class UnconfiguredResearchRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        plan_progress_callback=None,
    ) -> ResearchRuntimeRunResult:
        del session, plan_snapshot, plan_progress_callback
        raise RuntimeError("Research runtime runner 未配置")


class ResearchService:
    @staticmethod
    def _json_mapping_payload(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items()}

    def __init__(
        self,
        *,
        db: AsyncSession,
        planner: ResearchPlanner,
        runtime_runner: ResearchRuntimeRunner,
        finalizer: ResearchFinalizer,
        event_store: ResearchEventStore | None = None,
        artifact_store: ResearchArtifactStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._planner = planner
        self._runtime_runner = runtime_runner
        self._finalizer = finalizer
        self._event_store = event_store or ResearchEventStore(db)
        self._artifact_store = artifact_store or ResearchArtifactStore(db)
        self._settings = settings or get_settings()
        self._gate_thresholds = build_research_gate_thresholds(self._settings)

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        stmt = (
            select(ResearchSession)
            .where(ResearchSession.id == session_id)
            .options(
                selectinload(ResearchSession.artifacts),
                selectinload(ResearchSession.events),
                selectinload(ResearchSession.task_outbox_entries),
            )
        )
        session = (await self._db.execute(stmt)).scalar_one_or_none()
        if session is None:
            raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")
        return session

    def read_plan_snapshot(self, session: ResearchSession) -> ResearchPlanSnapshot:
        artifact = self._artifact_by_key(session, "plan_snapshot")
        payload = artifact.content_json
        if not isinstance(payload, dict):
            raise bad_request(
                code="RESEARCH_PLAN_SNAPSHOT_MISSING",
                message="研究计划快照不存在或格式无效",
            )
        return ResearchPlanSnapshot.model_validate(payload)

    def _read_plan_progress_payload(
        self, session: ResearchSession
    ) -> dict[str, object] | None:
        artifact = next(
            (
                item
                for item in session.artifacts
                if item.artifact_key == PLAN_PROGRESS_ARTIFACT_KEY
            ),
            None,
        )
        payload = artifact.content_json if artifact is not None else None
        return payload if isinstance(payload, dict) else None

    def _try_read_plan_snapshot(
        self, session: ResearchSession
    ) -> ResearchPlanSnapshot | None:
        artifact = next(
            (item for item in session.artifacts if item.artifact_key == "plan_snapshot"),
            None,
        )
        payload = artifact.content_json if artifact is not None else None
        if not isinstance(payload, dict):
            return None
        return ResearchPlanSnapshot.model_validate(payload)

    async def create_session(
        self,
        request: ResearchSessionCreateRequest,
        *,
        thread_id: str,
        session_id: uuid.UUID | None = None,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        session = ResearchSession(
            id=session_id,
            thread_id=thread_id,
            question=request.question,
            status=ResearchSessionStatus.CREATED,
            planner_phase="preflight",
        )
        self._db.add(session)
        await self._db.flush()
        ensure_research_trace_id(session)

        session.transition_to(ResearchSessionStatus.PLANNING)
        plan_result = await self._planner.build_plan(request)
        if plan_result.clarification_request is not None:
            await self._persist_clarification_request(
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
        await self._persist_planned_session_artifacts(
            session=session,
            plan_result=plan_result,
        )
        await self._event_store.append(
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
        self._ensure_dispatch_outbox(session=session)
        return session, plan_result

    async def _persist_clarification_request(
        self,
        *,
        session: ResearchSession,
        clarification_request: ResearchClarificationRequest,
    ) -> None:
        payload = clarification_request.model_dump(mode="json")
        await self._artifact_store.upsert(
            session=session,
            artifact_key="clarification_request",
            content_json=payload,
        )
        await self._event_store.append(
            session=session,
            event_type="research.clarification.requested",
            phase="planner",
            payload=payload,
            trace_id=session.trace_id,
        )

    async def _persist_clarification_answer(
        self,
        *,
        session: ResearchSession,
        answer: str,
    ) -> None:
        await self._artifact_store.upsert(
            session=session,
            artifact_key="clarification_answer",
            content_text=answer,
        )

    async def _persist_planned_session_artifacts(
        self,
        *,
        session: ResearchSession,
        plan_result: ResearchPlannerResult,
    ) -> None:
        plan_snapshot = plan_result.plan_snapshot
        if plan_snapshot is None:
            raise bad_request(
                code="RESEARCH_PLAN_SNAPSHOT_MISSING",
                message="研究计划快照缺失",
            )
        await self._artifact_store.upsert(
            session=session,
            artifact_key=plan_result.plan_artifact_key,
            content_json=plan_result.artifact_payload,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="research_brief",
            content_text=plan_snapshot.research_brief,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key=PLAN_PROGRESS_ARTIFACT_KEY,
            content_json=self._build_plan_progress_snapshot(
                plan_snapshot,
                current_step_index=None,
                completed_step_count=0,
            ),
        )
        bootstrap_artifacts = build_workspace_bootstrap_artifacts(
            session_id=session.id,
            question=session.question,
            plan_snapshot=plan_snapshot,
        )
        for seed in bootstrap_artifacts.values():
            await self._artifact_store.upsert(
                session=session,
                artifact_key=seed.artifact_key,
                content_text=seed.content_text,
                content_json=seed.content_json,
            )

    async def _persist_runtime_context_artifacts(
        self,
        *,
        session: ResearchSession,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> None:
        if runtime_context_snapshot is None:
            return

        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_claim_map_md",
            content_text=runtime_context_snapshot.claim_map_md,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_evidence_ledger_md",
            content_text=runtime_context_snapshot.evidence_ledger_md,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_analysis_notes_md",
            content_text=runtime_context_snapshot.analysis_notes_md,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_report_outline_md",
            content_text=runtime_context_snapshot.report_outline_md,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_report_draft_md",
            content_text=runtime_context_snapshot.report_draft_md,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_report_context_json",
            content_json=runtime_context_snapshot.report_context_json,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="runtime_files_snapshot_json",
            content_json=runtime_context_snapshot.files_snapshot,
        )

    async def submit_clarification(
        self,
        *,
        session: ResearchSession,
        answer: str,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        if session.status != ResearchSessionStatus.CLARIFYING:
            raise bad_request(
                code="RESEARCH_CLARIFICATION_NOT_ALLOWED",
                message="仅 clarifying 状态允许提交澄清",
            )
        effective_question = self._build_effective_planning_question(
            session=session,
            answer=answer,
        )
        await self._persist_clarification_answer(session=session, answer=answer)
        await self._event_store.append(
            session=session,
            event_type="research.clarification.submitted",
            phase="planner",
            payload={"answer": answer, "effective_question": effective_question},
            trace_id=session.trace_id,
        )
        plan_result = await self._planner.build_plan(
            ResearchSessionCreateRequest(question=effective_question)
        )
        if plan_result.clarification_request is not None:
            await self._persist_clarification_request(
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
        await self._persist_planned_session_artifacts(
            session=session,
            plan_result=plan_result,
        )
        await self._event_store.append(
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
        self._ensure_dispatch_outbox(session=session)
        return session, plan_result

    async def update_plan(
        self,
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
        await self._artifact_store.upsert(
            session=session,
            artifact_key="plan_feedback",
            content_text=normalized_feedback,
        )
        await self._event_store.append(
            session=session,
            event_type="research.plan.update_requested",
            phase="planner",
            payload={"feedback": normalized_feedback, "lc_agent_name": "planner"},
            trace_id=session.trace_id,
        )
        effective_question = self._build_effective_planning_question(
            session=session,
            answer=normalized_feedback,
        )
        plan_result = await self._planner.build_plan(
            ResearchSessionCreateRequest(question=effective_question)
        )
        if plan_result.clarification_request is not None:
            await self._persist_clarification_request(
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
        await self._persist_planned_session_artifacts(
            session=session,
            plan_result=plan_result,
        )
        await self._event_store.append(
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

    async def start_session(self, *, session: ResearchSession) -> ResearchSession:
        if session.status != ResearchSessionStatus.PLAN_READY:
            raise bad_request(
                code="RESEARCH_START_NOT_ALLOWED",
                message="仅 plan_ready 状态允许开始研究",
            )
        plan_snapshot = self.read_plan_snapshot(session)
        session.transition_to(ResearchSessionStatus.QUEUED)
        await self._event_store.append(
            session=session,
            event_type="research.run.queued",
            phase="planner",
            payload={"lc_agent_name": "planner"},
            trace_id=session.trace_id,
        )
        await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase="planner",
            current_step_index=1 if plan_snapshot.subtasks else None,
            completed_step_count=0,
        )
        self._ensure_dispatch_outbox(session=session)
        return session

    async def stop_session(
        self,
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
            plan_snapshot = self._try_read_plan_snapshot(session)
            if plan_snapshot is not None:
                await self._persist_terminal_plan_progress_snapshot(
                    session=session,
                    plan_snapshot=plan_snapshot,
                    phase="runtime" if runtime_stop else "planner",
                    terminal_state="canceled",
                )
            session.transition_to(ResearchSessionStatus.CANCELED)
            await self._event_store.append(
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

    @staticmethod
    def _build_effective_planning_question(
        *,
        session: ResearchSession,
        answer: str,
    ) -> str:
        normalized_question = str(session.question or "").strip()
        collected_answers: list[str] = []
        for event in sorted(session.events, key=lambda item: item.sequence):
            if event.event_type != "research.clarification.submitted":
                continue
            payload = event.payload
            if not isinstance(payload, dict):
                continue
            raw_answer = payload.get("answer")
            if isinstance(raw_answer, str) and raw_answer.strip():
                collected_answers.append(raw_answer.strip())
        if isinstance(answer, str) and answer.strip():
            collected_answers.append(answer.strip())
        if not collected_answers:
            return normalized_question
        return f"{normalized_question} {' '.join(collected_answers)}".strip()

    def _ensure_dispatch_outbox(self, *, session: ResearchSession) -> None:
        if session.status != ResearchSessionStatus.QUEUED:
            return
        existing = next(
            (
                item
                for item in session.task_outbox_entries
                if item.task_name == RESEARCH_SESSION_TASK_NAME
            ),
            None,
        )
        if existing is not None:
            if existing.status == ResearchTaskOutboxStatus.FAILED:
                existing.status = ResearchTaskOutboxStatus.PENDING
                existing.next_retry_at = None
                existing.dispatched_at = None
                existing.last_error = None
            return

        self._db.add(
            ResearchTaskOutbox(
                session_id=session.id,
                task_name=RESEARCH_SESSION_TASK_NAME,
                status=ResearchTaskOutboxStatus.PENDING,
                payload={},
            )
        )

    async def execute_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchFinalizerResult | None:
        ensure_research_trace_id(session)
        session.transition_to(ResearchSessionStatus.RUNNING)
        session.runtime_phase = "runtime"
        session.started_at = datetime.now(timezone.utc)
        await self._event_store.append(
            session=session,
            event_type="research.run.started",
            phase="runtime",
            payload={
                "target_sources": [item.value for item in plan_snapshot.target_sources],
                "lc_agent_name": "deep-research",
            },
            trace_id=session.trace_id,
        )
        await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase="runtime",
            current_step_index=1 if plan_snapshot.subtasks else None,
            completed_step_count=0,
        )

        runtime_result = await self._runtime_runner.run_session(
            session=session,
            plan_snapshot=plan_snapshot,
            plan_progress_callback=(
                self._build_runtime_plan_progress_callback(
                    session=session,
                    plan_snapshot=plan_snapshot,
                )
                if plan_snapshot.subtasks
                else None
            ),
        )
        source_bundle = runtime_result.source_bundle
        await self._append_trace_events(
            session=session,
            trace_links=build_trace_links(
                session=session, runtime_result=runtime_result
            ),
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="source_bundle",
            content_json={
                "target_sources": [item.value for item in source_bundle.target_sources],
                "findings": list(source_bundle.findings),
                "citations": [
                    citation.model_dump(mode="json")
                    for citation in source_bundle.citations
                ],
                "provider_counts": source_bundle.provider_counts,
            },
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="interim_findings",
            content_json=list(source_bundle.findings),
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="interim_summary",
            content_text=source_bundle.interim_summary,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="coverage_gaps",
            content_json=list(source_bundle.coverage_gaps),
        )
        await self._persist_runtime_context_artifacts(
            session=session,
            runtime_context_snapshot=runtime_result.runtime_context_snapshot,
        )

        committed_status = await self._read_committed_session_status(session=session)
        if committed_status == ResearchSessionStatus.CANCELED:
            if session.status != ResearchSessionStatus.CANCELED:
                session.transition_to(ResearchSessionStatus.CANCELED)
            if session.finished_at is None:
                session.finished_at = datetime.now(timezone.utc)
            return None

        session.transition_to(ResearchSessionStatus.FINALIZING)
        session.finalizer_phase = "finalizer"
        await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase="finalizer",
            current_step_index=None,
            completed_step_count=len(plan_snapshot.subtasks),
        )
        await self._event_store.append(
            session=session,
            event_type="research.finalizer.started",
            phase="finalizer",
            payload={
                "coverage_gaps": list(source_bundle.coverage_gaps),
                "lc_agent_name": "finalizer",
            },
            trace_id=session.trace_id,
        )

        final_result = self._finalizer.finalize(
            question=session.question,
            target_sources=plan_snapshot.target_sources,
            source_bundle=source_bundle,
            runtime_context_snapshot=runtime_result.runtime_context_snapshot,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="report_json",
            content_json=final_result.report_json,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="report_md",
            content_text=final_result.report_md,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="claim_map_json",
            content_json=final_result.report_json["claim_map"],
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="coverage_matrix_json",
            content_json=final_result.report_json["coverage_matrix"],
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="conflicts_json",
            content_json=final_result.report_json["conflicts"],
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="source_ledger_json",
            content_json=final_result.report_json["source_ledger"],
        )
        session.transition_to(ResearchSessionStatus.FINAL)
        session.finished_at = datetime.now(timezone.utc)
        await self._event_store.append(
            session=session,
            event_type="research.final.completed",
            phase="finalizer",
            payload={
                "artifact_keys": [
                    "report_json",
                    "report_md",
                    "claim_map_json",
                    "coverage_matrix_json",
                    "conflicts_json",
                    "source_ledger_json",
                ],
                "lc_agent_name": "finalizer",
            },
            trace_id=session.trace_id,
        )
        metrics = build_research_metrics(
            session=session,
            plan_snapshot=plan_snapshot,
            runtime_result=runtime_result,
        )
        replay = evaluate_research_replay_consistency(
            session=session,
            events=self.list_event_envelopes(session),
        )
        metrics["replay"] = replay
        metrics["gate"] = evaluate_research_gate(
            metrics=metrics,
            thresholds=self._gate_thresholds,
        )
        await self._persist_metrics_artifacts(session=session, metrics=metrics)
        return final_result

    async def fail_session(
        self,
        *,
        session: ResearchSession,
        exc: Exception,
        phase: str,
        source_provider: str | None = None,
    ) -> ResearchSession:
        ensure_research_trace_id(session)
        if not session.status.is_terminal():
            plan_snapshot = self._try_read_plan_snapshot(session)
            if plan_snapshot is not None:
                await self._persist_terminal_plan_progress_snapshot(
                    session=session,
                    plan_snapshot=plan_snapshot,
                    phase=phase,
                    terminal_state="failed",
                )
            session.transition_to(ResearchSessionStatus.FAILED)
        session.error_message = str(exc)
        session.finished_at = datetime.now(timezone.utc)
        fault = classify_research_fault(exc, source_provider=source_provider)
        await self._event_store.append(
            session=session,
            event_type="research.run.failed",
            phase=phase,
            payload={
                "error": str(exc),
                "fault": fault,
                "lc_agent_name": "deep-research",
                "source_provider": source_provider,
            },
            trace_id=session.trace_id,
        )
        metrics = build_failure_metrics(
            session=session,
            fault=fault,
            thresholds=self._gate_thresholds,
            existing_metrics=session.metrics
            if isinstance(session.metrics, dict)
            else None,
        )
        await self._persist_metrics_artifacts(session=session, metrics=metrics)
        return session

    def list_event_envelopes(
        self,
        session: ResearchSession,
        *,
        after_event_id: str | None = None,
    ) -> list[ResearchEventEnvelope]:
        events = sorted(session.events, key=lambda item: item.sequence)
        after_sequence = 0
        if after_event_id is not None:
            matched = next(
                (item for item in events if item.event_id == after_event_id), None
            )
            if matched is not None:
                after_sequence = matched.sequence
        return [
            self._build_event_envelope(session=session, event=event)
            for event in events
            if event.sequence > after_sequence
        ]

    def build_artifacts_response(
        self, session: ResearchSession
    ) -> ResearchArtifactsResponse:
        items = [
            ResearchArtifactRead(
                artifact_key=artifact.artifact_key,
                content_text=artifact.content_text,
                content_json=artifact.content_json,
                citations=self._extract_artifact_citations(artifact),
                source_provider=artifact.source_provider,
                retrieval_method=artifact.retrieval_method,
                origin_url=artifact.origin_url,
            )
            for artifact in sorted(
                session.artifacts, key=lambda item: item.artifact_key
            )
        ]
        items.append(
            ResearchArtifactRead(
                artifact_key="presentation_snapshot",
                content_json=build_research_presentation_snapshot(
                    session=session,
                    events=self.list_event_envelopes(session),
                    artifacts=items,
                ),
                citations=[],
            )
        )
        return ResearchArtifactsResponse(session_id=session.id, items=items)

    async def _append_trace_events(
        self,
        *,
        session: ResearchSession,
        trace_links: list[dict[str, object]],
    ) -> None:
        for item in trace_links:
            namespace = str(item.get("namespace") or "main")
            lc_agent_name = str(item.get("lc_agent_name") or "").strip()
            source_provider = item.get("source_provider")
            if namespace == "main" and lc_agent_name == "deep-research":
                continue
            await self._event_store.append(
                session=session,
                event_type="research.trace.recorded",
                phase="runtime",
                namespace=namespace,
                payload={
                    "lc_agent_name": lc_agent_name,
                    "source_provider": source_provider,
                },
                trace_id=str(item.get("trace_id") or session.trace_id or ""),
            )

    async def _persist_metrics_artifacts(
        self,
        *,
        session: ResearchSession,
        metrics: dict[str, object],
    ) -> None:
        session.metrics = dict(metrics)
        await self._artifact_store.upsert(
            session=session,
            artifact_key="metrics_snapshot",
            content_json=dict(metrics),
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="gate_snapshot",
            content_json=self._json_mapping_payload(metrics.get("gate")),
        )

    async def _read_committed_session_status(
        self,
        *,
        session: ResearchSession,
    ) -> ResearchSessionStatus | None:
        if session.id is None or not callable(getattr(self._db, "scalar", None)):
            return None

        stmt = select(ResearchSession.status).where(ResearchSession.id == session.id)
        no_autoflush = getattr(self._db, "no_autoflush", None)
        if no_autoflush is None:
            resolved_status = await self._db.scalar(stmt)
        else:
            with no_autoflush:
                resolved_status = await self._db.scalar(stmt)

        if isinstance(resolved_status, ResearchSessionStatus):
            return resolved_status
        if isinstance(resolved_status, str):
            try:
                return ResearchSessionStatus(resolved_status)
            except ValueError:
                return None
        return None

    @staticmethod
    def _artifact_by_key(
        session: ResearchSession, artifact_key: str
    ) -> ResearchArtifact:
        artifact = next(
            (item for item in session.artifacts if item.artifact_key == artifact_key),
            None,
        )
        if artifact is None:
            raise bad_request(
                code="RESEARCH_ARTIFACT_MISSING",
                message=f"研究工件缺失：{artifact_key}",
            )
        return artifact

    @staticmethod
    def _extract_artifact_citations(
        artifact: ResearchArtifact,
    ) -> list[ResearchCanonicalCitation]:
        payload = artifact.content_json
        if not isinstance(payload, dict):
            return []
        raw_citations = payload.get("citations")
        if not isinstance(raw_citations, list):
            return []
        return [
            ResearchCanonicalCitation.model_validate(item)
            for item in raw_citations
            if isinstance(item, dict)
        ]

    @staticmethod
    def _plan_progress_updated_at() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_plan_progress_index(
        value: object,
        *,
        total_steps: int,
    ) -> int | None:
        if not isinstance(value, int):
            return None
        if value < 1 or value > total_steps:
            return None
        return value

    @staticmethod
    def _extract_plan_progress_position(
        payload: dict[str, object] | None,
        *,
        total_steps: int,
    ) -> tuple[int | None, int]:
        if payload is None:
            return (1 if total_steps > 0 else None, 0)

        raw_completed = payload.get("completed_step_count")
        completed = raw_completed if isinstance(raw_completed, int) else 0
        completed = max(0, min(completed, total_steps))

        current = ResearchService._normalize_plan_progress_index(
            payload.get("current_step_index"),
            total_steps=total_steps,
        )
        if current is None and completed < total_steps:
            current = completed + 1 if total_steps > 0 else None
        if current is not None and current <= completed:
            current = None
        return current, completed

    @staticmethod
    def _build_plan_progress_snapshot(
        plan_snapshot: ResearchPlanSnapshot,
        *,
        current_step_index: int | None,
        completed_step_count: int,
        active_step_status: str = "current",
    ) -> dict[str, object]:
        total_steps = len(plan_snapshot.subtasks)
        bounded_completed = max(0, min(completed_step_count, total_steps))
        bounded_current = ResearchService._normalize_plan_progress_index(
            current_step_index, total_steps=total_steps
        )
        if bounded_current is not None and bounded_current <= bounded_completed:
            bounded_current = None

        steps: list[dict[str, object]] = []
        for index, subtask in enumerate(plan_snapshot.subtasks, start=1):
            if index <= bounded_completed:
                status = "complete"
            elif bounded_current is not None and index == bounded_current:
                status = active_step_status
            else:
                status = "pending"
            steps.append(
                {
                    "index": index,
                    "title": subtask.title,
                    "description": subtask.description,
                    "target_sources": [item.value for item in subtask.target_sources],
                    "status": status,
                }
            )

        return {
            "steps": steps,
            "current_step_index": bounded_current,
            "completed_step_count": bounded_completed,
            "updated_at": ResearchService._plan_progress_updated_at(),
        }

    @staticmethod
    def _lc_agent_name_for_phase(phase: str) -> str:
        if phase == "planner":
            return "planner"
        if phase == "finalizer":
            return "finalizer"
        return "deep-research"

    @staticmethod
    def _build_plan_progress_summary(snapshot: dict[str, object]) -> str:
        steps = snapshot.get("steps")
        if not isinstance(steps, list):
            return "研究计划步骤已更新。"

        current_step = next(
            (
                item
                for item in steps
                if isinstance(item, dict)
                and item.get("status") in {"current", "failed", "canceled"}
            ),
            None,
        )
        if isinstance(current_step, dict):
            title = str(current_step.get("title") or "").strip()
            status = str(current_step.get("status") or "")
            if status == "failed":
                return f"当前计划步骤失败：{title}" if title else "当前计划步骤失败。"
            if status == "canceled":
                return f"当前计划步骤已停止：{title}" if title else "当前计划步骤已停止。"
            return f"当前计划步骤：{title}" if title else "当前计划步骤已更新。"

        completed = snapshot.get("completed_step_count")
        if isinstance(completed, int) and completed == len(steps) and len(steps) > 0:
            return "研究计划步骤已全部完成，正在生成报告。"
        return "研究计划步骤已更新。"

    @staticmethod
    def _normalize_plan_progress_message(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _plan_progress_snapshot_equals(
        left: dict[str, object] | None,
        right: dict[str, object],
    ) -> bool:
        if left is None:
            return False
        return (
            left.get("steps") == right.get("steps")
            and left.get("current_step_index") == right.get("current_step_index")
            and left.get("completed_step_count") == right.get("completed_step_count")
        )

    async def _persist_plan_progress_snapshot(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        phase: str,
        current_step_index: int | None,
        completed_step_count: int,
        active_step_status: str = "current",
        event_message: str | None = None,
        emit_event: bool = True,
    ) -> dict[str, object]:
        normalized_message = self._normalize_plan_progress_message(event_message)
        existing_payload = self._read_plan_progress_payload(session)
        snapshot = self._build_plan_progress_snapshot(
            plan_snapshot,
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=active_step_status,
        )
        if (
            self._plan_progress_snapshot_equals(existing_payload, snapshot)
            and normalized_message is None
        ):
            return existing_payload if existing_payload is not None else snapshot
        await self._artifact_store.upsert(
            session=session,
            artifact_key=PLAN_PROGRESS_ARTIFACT_KEY,
            content_json=snapshot,
        )
        summary = normalized_message or self._build_plan_progress_summary(snapshot)
        if emit_event:
            await self._event_store.append(
                session=session,
                event_type=PLAN_PROGRESS_EVENT_TYPE,
                phase=phase,
                payload={
                    **snapshot,
                    "summary": summary,
                    "message": normalized_message,
                    "lc_agent_name": self._lc_agent_name_for_phase(phase),
                },
                trace_id=session.trace_id,
            )
        return snapshot

    async def _persist_terminal_plan_progress_snapshot(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        phase: str,
        terminal_state: str,
    ) -> dict[str, object]:
        existing_payload = self._read_plan_progress_payload(session)
        current_step_index, completed_step_count = self._extract_plan_progress_position(
            existing_payload,
            total_steps=len(plan_snapshot.subtasks),
        )
        return await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase=phase,
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=terminal_state,
        )

    async def _advance_runtime_plan_progress(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        update: ResearchPlanProgressUpdate,
    ) -> dict[str, object]:
        total_steps = len(plan_snapshot.subtasks)
        step_index = self._normalize_plan_progress_index(
            update.step_index,
            total_steps=total_steps,
        )
        if step_index is None:
            raise RuntimeError(
                f"计划步骤索引超出范围: {update.step_index}/{total_steps}"
            )

        existing_payload = self._read_plan_progress_payload(session)
        _, completed_step_count = self._extract_plan_progress_position(
            existing_payload,
            total_steps=total_steps,
        )

        current_step_index: int | None = step_index
        active_step_status = update.status
        if update.status == "complete":
            completed_step_count = max(completed_step_count, step_index)
            current_step_index = (
                completed_step_count + 1
                if completed_step_count < total_steps
                else None
            )
            active_step_status = "current"

        return await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase="runtime",
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=active_step_status,
            event_message=update.message,
        )

    def _build_runtime_plan_progress_callback(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ):
        async def _callback(update: ResearchPlanProgressUpdate) -> None:
            await self._advance_runtime_plan_progress(
                session=session,
                plan_snapshot=plan_snapshot,
                update=update,
            )

        return _callback

    @staticmethod
    def _build_event_envelope(
        *,
        session: ResearchSession,
        event: ResearchEvent,
    ) -> ResearchEventEnvelope:
        payload = dict(event.payload or {})
        source_provider = payload.get("source_provider")
        retrieval_method = payload.get("retrieval_method")
        origin_url = payload.get("origin_url")
        lc_agent_name = payload.get("lc_agent_name")
        subagent_name = payload.get("subagent_name")
        if not isinstance(subagent_name, str) or not subagent_name.strip():
            subagent_name = ResearchService._subagent_name_from_namespace(
                event.namespace
            )
        return ResearchEventEnvelope(
            event_id=event.event_id,
            sequence=event.sequence,
            timestamp=event.created_at,
            event_type=event.event_type,
            session_id=session.id,
            phase=event.phase,
            namespace=event.namespace,
            payload=payload,
            trace_id=event.trace_id,
            source_provider=source_provider
            if isinstance(source_provider, str)
            else None,
            retrieval_method=retrieval_method
            if isinstance(retrieval_method, str)
            else None,
            origin_url=origin_url if isinstance(origin_url, str) else None,
            lc_agent_name=lc_agent_name if isinstance(lc_agent_name, str) else None,
            subagent_name=subagent_name if isinstance(subagent_name, str) else None,
        )

    @staticmethod
    def _subagent_name_from_namespace(namespace: str) -> str | None:
        normalized = str(namespace or "").strip("/")
        if not normalized or normalized == "main":
            return None
        parts = [item for item in normalized.split("/") if item]
        return parts[-1] if parts else None


def build_research_service(
    *,
    db: AsyncSession,
    runtime_runner: ResearchRuntimeRunner | None = None,
) -> ResearchService:
    return ResearchService(
        db=db,
        planner=ResearchPlanner(),
        runtime_runner=runtime_runner or UnconfiguredResearchRuntimeRunner(),
        finalizer=ResearchFinalizer(),
        settings=get_settings(),
    )
