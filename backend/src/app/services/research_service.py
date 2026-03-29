"""Research session orchestration service。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import ResearchPlanSnapshot, ResearchSessionCreateRequest
from app.services.research_artifact_store import ResearchArtifactStore
from app.services.research_event_store import ResearchEventStore
from app.services.research_finalizer import ResearchFinalizer, ResearchFinalizerResult
from app.services.research_planner import ResearchPlanner
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_source_bundle import ResearchSourceBundle


class ResearchRuntimeRunner(Protocol):
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchSourceBundle: ...


class ResearchService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        planner: ResearchPlanner,
        runtime_runner: ResearchRuntimeRunner,
        finalizer: ResearchFinalizer,
        event_store: ResearchEventStore | None = None,
        artifact_store: ResearchArtifactStore | None = None,
    ) -> None:
        self._db = db
        self._planner = planner
        self._runtime_runner = runtime_runner
        self._finalizer = finalizer
        self._event_store = event_store or ResearchEventStore(db)
        self._artifact_store = artifact_store or ResearchArtifactStore(db)

    async def create_session(
        self,
        request: ResearchSessionCreateRequest,
        *,
        thread_id: str,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        session = ResearchSession(
            thread_id=thread_id,
            question=request.question,
            selected_kb_ids=request.selected_kb_ids,
            allow_external=request.allow_external,
            status=ResearchSessionStatus.CREATED,
            planner_phase="preflight",
        )
        self._db.add(session)
        await self._db.flush()

        session.transition_to(ResearchSessionStatus.PLANNING)
        plan_result = self._planner.build_plan(request)
        await self._artifact_store.upsert(
            session=session,
            artifact_key=plan_result.plan_artifact_key,
            content_json=plan_result.artifact_payload,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="research_brief",
            content_text=plan_result.plan_snapshot.research_brief,
        )
        await self._event_store.append(
            session=session,
            event_type="research.plan.created",
            phase="planner",
            payload=plan_result.artifact_payload,
            trace_id=session.trace_id,
        )
        session.transition_to(plan_result.next_status)
        return session, plan_result

    async def confirm_plan(
        self,
        *,
        session: ResearchSession,
        approved: bool,
        note: str | None = None,
    ) -> ResearchSession:
        event_type = "research.plan.confirmed" if approved else "research.plan.rejected"
        await self._event_store.append(
            session=session,
            event_type=event_type,
            phase="planner",
            payload={"approved": approved, "note": note},
            trace_id=session.trace_id,
        )
        session.transition_to(
            ResearchSessionStatus.QUEUED if approved else ResearchSessionStatus.CANCELED
        )
        return session

    async def execute_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchFinalizerResult:
        session.transition_to(ResearchSessionStatus.RUNNING)
        session.runtime_phase = "runtime"
        session.started_at = datetime.now(timezone.utc)
        await self._event_store.append(
            session=session,
            event_type="research.run.started",
            phase="runtime",
            payload={"target_sources": [item.value for item in plan_snapshot.target_sources]},
            trace_id=session.trace_id,
        )

        source_bundle = await self._runtime_runner.run_session(
            session=session,
            plan_snapshot=plan_snapshot,
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

        session.transition_to(ResearchSessionStatus.FINALIZING)
        session.finalizer_phase = "finalizer"
        await self._event_store.append(
            session=session,
            event_type="research.finalizer.started",
            phase="finalizer",
            payload={"coverage_gaps": list(source_bundle.coverage_gaps)},
            trace_id=session.trace_id,
        )

        final_result = self._finalizer.finalize(
            question=session.question,
            target_sources=plan_snapshot.target_sources,
            source_bundle=source_bundle,
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
        session.transition_to(ResearchSessionStatus.FINAL)
        session.finished_at = datetime.now(timezone.utc)
        await self._event_store.append(
            session=session,
            event_type="research.final.completed",
            phase="finalizer",
            payload={"artifact_keys": ["report_json", "report_md"]},
            trace_id=session.trace_id,
        )
        return final_result

    async def interrupt_session(
        self,
        *,
        session: ResearchSession,
        reason: str | None = None,
    ) -> ResearchSession:
        session.transition_to(ResearchSessionStatus.INTERRUPTED)
        await self._event_store.append(
            session=session,
            event_type="research.run.interrupted",
            phase="runtime",
            payload={"reason": reason},
            trace_id=session.trace_id,
        )
        return session

    async def resume_session(
        self,
        *,
        session: ResearchSession,
        idempotency_key: str,
        resume_from_event_id: str | None = None,
        decisions: list[dict] | None = None,
    ) -> dict:
        if session.last_resume_idempotency_key == idempotency_key:
            return dict(session.last_resume_response or {})
        session.transition_to(ResearchSessionStatus.RESUMING)
        response = {
            "status": "accepted",
            "resume_from_event_id": resume_from_event_id,
            "decision_count": len(decisions or []),
        }
        await self._event_store.append(
            session=session,
            event_id=f"resume:{idempotency_key}",
            event_type="research.run.resume_requested",
            phase="runtime",
            payload={
                "idempotency_key": idempotency_key,
                "resume_from_event_id": resume_from_event_id,
                "decisions": list(decisions or []),
            },
            trace_id=session.trace_id,
            idempotency_key=idempotency_key,
        )
        session.last_resume_idempotency_key = idempotency_key
        session.last_resume_response = response
        return dict(response)
