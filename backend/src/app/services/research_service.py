"""Research session orchestration service。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import bad_request, not_found
from app.models.research_artifact import ResearchArtifact
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchArtifactRead,
    ResearchArtifactsResponse,
    ResearchCanonicalCitation,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchSessionCreateRequest,
)
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


class UnconfiguredResearchRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchSourceBundle:
        del session, plan_snapshot
        raise RuntimeError("Research runtime runner 未配置")


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

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        stmt = (
            select(ResearchSession)
            .where(ResearchSession.id == session_id)
            .options(
                selectinload(ResearchSession.artifacts),
                selectinload(ResearchSession.events),
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

    def list_event_envelopes(
        self,
        session: ResearchSession,
        *,
        after_event_id: str | None = None,
    ) -> list[ResearchEventEnvelope]:
        events = sorted(session.events, key=lambda item: item.sequence)
        after_sequence = 0
        if after_event_id is not None:
            matched = next((item for item in events if item.event_id == after_event_id), None)
            if matched is not None:
                after_sequence = matched.sequence
        return [
            self._build_event_envelope(session=session, event=event)
            for event in events
            if event.sequence > after_sequence
        ]

    def build_artifacts_response(self, session: ResearchSession) -> ResearchArtifactsResponse:
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
            for artifact in sorted(session.artifacts, key=lambda item: item.artifact_key)
        ]
        return ResearchArtifactsResponse(session_id=session.id, items=items)

    @staticmethod
    def _artifact_by_key(session: ResearchSession, artifact_key: str) -> ResearchArtifact:
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
    def _extract_artifact_citations(artifact: ResearchArtifact) -> list[ResearchCanonicalCitation]:
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
    def _build_event_envelope(
        *,
        session: ResearchSession,
        event: ResearchEvent,
    ) -> ResearchEventEnvelope:
        payload = dict(event.payload or {})
        source_provider = payload.get("source_provider")
        retrieval_method = payload.get("retrieval_method")
        origin_url = payload.get("origin_url")
        subagent_name = payload.get("subagent_name")
        if not isinstance(subagent_name, str) or not subagent_name.strip():
            subagent_name = ResearchService._subagent_name_from_namespace(event.namespace)
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
            source_provider=source_provider if isinstance(source_provider, str) else None,
            retrieval_method=retrieval_method if isinstance(retrieval_method, str) else None,
            origin_url=origin_url if isinstance(origin_url, str) else None,
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
    )
