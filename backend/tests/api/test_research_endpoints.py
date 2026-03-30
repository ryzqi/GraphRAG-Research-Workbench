from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.api import api_router
from app.core.errors import register_exception_handlers
from app.db.session import get_db_session
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchArtifactRead,
    ResearchArtifactsResponse,
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_planner_types import ResearchPlannerResult


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeResearchService:
    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, ResearchSession] = {}
        self.plan_snapshots: dict[uuid.UUID, ResearchPlanSnapshot] = {}
        self.event_envelopes: dict[uuid.UUID, list[ResearchEventEnvelope]] = {}
        self.artifacts: dict[uuid.UUID, list[ResearchArtifactRead]] = {}

    async def create_session(
        self,
        request: ResearchSessionCreateRequest,
        *,
        thread_id: str,
        session_id: uuid.UUID | None = None,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        resolved_session_id = session_id or uuid.uuid4()
        clarification_request = self._maybe_build_clarification_request(request.question)
        confirmation_required = clarification_request is None
        session = ResearchSession(
            id=resolved_session_id,
            thread_id=thread_id,
            question=request.question,
            status=(
                ResearchSessionStatus.CLARIFYING
                if clarification_request is not None
                else ResearchSessionStatus.AWAITING_CONFIRMATION
            ),
        )
        self.sessions[resolved_session_id] = session
        if clarification_request is not None:
            self.event_envelopes[resolved_session_id] = [
                ResearchEventEnvelope(
                    event_id="evt-000001",
                    sequence=1,
                    timestamp="2026-03-29T00:00:00Z",
                    event_type="research.clarification.requested",
                    session_id=resolved_session_id,
                    phase="planner",
                    namespace="main",
                    payload=clarification_request.model_dump(mode="json"),
                )
            ]
            self.artifacts[resolved_session_id] = [
                ResearchArtifactRead(
                    artifact_key="clarification_request",
                    content_json=clarification_request.model_dump(mode="json"),
                )
            ]
            return session, ResearchPlannerResult(
                plan_snapshot=None,
                clarification_request=clarification_request,
                auto_approve=False,
                next_status=session.status,
            )

        plan_snapshot = ResearchPlanSnapshot(
            research_brief=f"围绕“{request.question}”执行研究。",
            complexity="simple",
            summary="先规划，再决定是否直接排队执行。",
            target_sources=[ResearchSourceTarget.WEB],
            subtasks=[
                ResearchPlanSubtask(
                    title="收集网页证据",
                    description="验证 research API 当前端点契约。",
                    target_sources=[ResearchSourceTarget.WEB],
                )
            ],
            confirmation_required=confirmation_required,
        )
        self.plan_snapshots[resolved_session_id] = plan_snapshot
        self.event_envelopes[resolved_session_id] = [
            ResearchEventEnvelope(
                event_id="evt-000001",
                sequence=1,
                timestamp="2026-03-29T00:00:00Z",
                event_type="research.plan.created",
                session_id=resolved_session_id,
                phase="planner",
                namespace="main",
                payload={"question": request.question},
            )
        ]
        self.artifacts[resolved_session_id] = [
            ResearchArtifactRead(
                artifact_key="plan_snapshot",
                content_json=plan_snapshot.model_dump(mode="json"),
            )
        ]
        return session, ResearchPlannerResult(
            plan_snapshot=plan_snapshot,
            clarification_request=None,
            auto_approve=False,
            next_status=session.status,
        )

    @staticmethod
    def _maybe_build_clarification_request(
        question: str,
    ) -> ResearchClarificationRequest | None:
        if "帮我研究一下" not in question:
            return None
        return ResearchClarificationRequest(
            summary="当前问题过于宽泛，需要先补充研究范围。",
            questions=[
                ResearchClarificationQuestion(
                    id="scope",
                    question="希望聚焦在哪类 AI 编程工具或具体使用场景？",
                    why_it_matters="范围过大时无法确定检索重点与最终输出结构。",
                )
            ],
        )

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        return self.sessions[session_id]

    def read_plan_snapshot(self, session: ResearchSession) -> ResearchPlanSnapshot:
        return self.plan_snapshots[session.id]

    async def confirm_plan(
        self,
        *,
        session: ResearchSession,
        approved: bool,
        note: str | None = None,
    ) -> ResearchSession:
        session.status = ResearchSessionStatus.QUEUED if approved else ResearchSessionStatus.CANCELED
        self.event_envelopes[session.id].append(
            ResearchEventEnvelope(
                event_id="evt-000002",
                sequence=2,
                timestamp="2026-03-29T00:01:00Z",
                event_type=(
                    "research.plan.confirmed"
                    if approved
                    else "research.plan.rejected"
                ),
                session_id=session.id,
                phase="planner",
                namespace="main",
                payload={"approved": approved, "note": note},
            )
        )
        return session

    async def interrupt_session(
        self,
        *,
        session: ResearchSession,
        reason: str | None = None,
    ) -> ResearchSession:
        session.status = ResearchSessionStatus.INTERRUPTED
        self.event_envelopes[session.id].append(
            ResearchEventEnvelope(
                event_id="evt-000003",
                sequence=3,
                timestamp="2026-03-29T00:02:00Z",
                event_type="research.run.interrupted",
                session_id=session.id,
                phase="runtime",
                namespace="main",
                payload={"reason": reason},
            )
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
        session.status = ResearchSessionStatus.RESUMING
        self.event_envelopes[session.id].append(
            ResearchEventEnvelope(
                event_id="evt-000004",
                sequence=4,
                timestamp="2026-03-29T00:03:00Z",
                event_type="research.run.resume_requested",
                session_id=session.id,
                phase="runtime",
                namespace="main",
                payload={
                    "idempotency_key": idempotency_key,
                    "resume_from_event_id": resume_from_event_id,
                    "decisions": decisions or [],
                },
            )
        )
        return {
            "status": "accepted",
            "resume_from_event_id": resume_from_event_id,
            "decision_count": len(decisions or []),
        }

    def list_event_envelopes(
        self,
        session: ResearchSession,
        *,
        after_event_id: str | None = None,
    ) -> list[ResearchEventEnvelope]:
        items = list(self.event_envelopes[session.id])
        if not after_event_id:
            return items
        index = next(
            (
                idx
                for idx, item in enumerate(items)
                if item.event_id == after_event_id
            ),
            None,
        )
        if index is None:
            return items
        return items[index + 1 :]

    def build_artifacts_response(self, session: ResearchSession) -> ResearchArtifactsResponse:
        return ResearchArtifactsResponse(
            session_id=session.id,
            items=list(self.artifacts[session.id]),
        )


@contextmanager
def _build_test_client(
    *,
    service: _FakeResearchService,
    db: _FakeAsyncSession,
    dispatched: list[str],
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    app.state.research_service_factory = lambda *, db, request: service
    app.state.research_dispatcher = lambda session_id: dispatched.append(str(session_id))

    async def _override_db():
        yield db

    app.dependency_overrides[get_db_session] = _override_db
    with TestClient(app) as client:
        yield client


def test_api_router_exposes_current_research_routes() -> None:
    route_paths = {route.path for route in api_router.routes}

    assert "/research/sessions" in route_paths
    assert "/research/sessions/{session_id}/confirm-plan" in route_paths
    assert "/research/sessions/{session_id}/stream" in route_paths
    assert "/research/sessions/{session_id}/interrupt" in route_paths
    assert "/research/sessions/{session_id}/resume" in route_paths
    assert "/research/sessions/{session_id}/artifacts" in route_paths
    assert not any(path.startswith("/research/runs") for path in route_paths)


def test_create_session_returns_plan_snapshot_and_dispatches_worker_when_auto_approved() -> None:
    service = _FakeResearchService()
    db = _FakeAsyncSession()
    dispatched: list[str] = []

    with _build_test_client(service=service, db=db, dispatched=dispatched) as client:
        response = client.post(
            "/api/v1/research/sessions",
            json={
                "question": "给出 research API 当前端点集合",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == ResearchSessionStatus.AWAITING_CONFIRMATION.value
    assert payload["plan_snapshot"]["research_brief"] == "围绕“给出 research API 当前端点集合”执行研究。"
    assert dispatched == []
    assert db.commit_calls == 1


def test_create_session_returns_clarifying_status_without_dispatch_for_unclear_prompt() -> None:
    service = _FakeResearchService()
    db = _FakeAsyncSession()
    dispatched: list[str] = []

    with _build_test_client(service=service, db=db, dispatched=dispatched) as client:
        response = client.post(
            "/api/v1/research/sessions",
            json={"question": "帮我研究一下 AI 编程工具"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "clarifying"
    assert payload["clarification_request"]["questions"][0]["id"] == "scope"
    assert dispatched == []


def test_confirm_plan_stream_interrupt_resume_and_artifacts_flow() -> None:
    service = _FakeResearchService()
    db = _FakeAsyncSession()
    dispatched: list[str] = []

    with _build_test_client(service=service, db=db, dispatched=dispatched) as client:
        create_response = client.post(
            "/api/v1/research/sessions",
            json={
                "question": "确认 research 计划",
            },
        )
        session_id = create_response.json()["session_id"]

        confirm_response = client.post(
            f"/api/v1/research/sessions/{session_id}/confirm-plan",
            json={"approved": True, "note": "继续执行"},
        )
        assert confirm_response.status_code == 200
        assert confirm_response.json()["status"] == ResearchSessionStatus.QUEUED.value
        assert dispatched == [session_id]

        with client.stream(
            "GET",
            f"/api/v1/research/sessions/{session_id}/stream",
            headers={"Last-Event-ID": "evt-000001"},
        ) as stream_response:
            stream_text = "".join(stream_response.iter_text())
        assert stream_response.status_code == 200
        assert "evt-000002" in stream_text
        assert "evt-000001" not in stream_text

        interrupt_response = client.post(
            f"/api/v1/research/sessions/{session_id}/interrupt",
            json={"reason": "等待确认"},
        )
        assert interrupt_response.status_code == 200
        assert interrupt_response.json()["status"] == ResearchSessionStatus.INTERRUPTED.value

        resume_response = client.post(
            f"/api/v1/research/sessions/{session_id}/resume",
            json={
                "idempotency_key": "resume-1",
                "resume_from_event_id": "evt-000003",
                "decisions": [{"action": "approve"}],
            },
        )
        assert resume_response.status_code == 200
        assert resume_response.json() == {
            "status": "accepted",
            "resume_from_event_id": "evt-000003",
            "decision_count": 1,
        }
        assert dispatched == [session_id, session_id]

        artifacts_response = client.get(
            f"/api/v1/research/sessions/{session_id}/artifacts"
        )
        assert artifacts_response.status_code == 200
        assert artifacts_response.json()["items"][0]["artifact_key"] == "plan_snapshot"

    assert db.commit_calls == 4
