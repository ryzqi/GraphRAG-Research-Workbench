from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.api import api_router
from app.core.errors import register_exception_handlers
from app.db.session import get_db_session
from app.main import app as main_app
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchArtifactRead,
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
    ResearchComplexity,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
)
from app.services.research_planner import ResearchPlanner, ResearchScoper
from app.services.research_planner_types import ResearchPlannerResult


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


class _SequenceScoper(ResearchScoper):
    def __init__(self, outputs: list[ResearchClarificationRequest | ResearchPlanSnapshot]) -> None:
        self.outputs = list(outputs)

    async def scope(
        self,
        *,
        question: str,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
        if not self.outputs:
            raise AssertionError(f"missing scoper output for question: {question}")
        return self.outputs.pop(0)


def _build_plan_snapshot(question: str) -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief=f"围绕“{question}”生成可直接执行的研究计划。",
        complexity=ResearchComplexity.COMPARATIVE,
        summary="先整理目标边界，再收集证据并输出结论。",
        target_sources=["web"],
        subtasks=[
            ResearchPlanSubtask(
                title="锁定研究边界",
                description="明确问题边界、比较维度与输出结构。",
                target_sources=["web"],
            )
        ],
        budget_guidance="优先官方文档与高可信资料。",
    )


class _FakeResearchService:
    def __init__(self, *, planner: ResearchPlanner | None = None) -> None:
        self._planner = planner or ResearchPlanner(scoper=_SequenceScoper([_build_plan_snapshot("default")]))
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
        plan_result = await self._planner.build_plan(request)
        session = ResearchSession(
            id=resolved_session_id,
            thread_id=thread_id,
            question=request.question,
            status=plan_result.next_status,
        )
        self.sessions[resolved_session_id] = session
        if plan_result.clarification_request is not None:
            self.event_envelopes[resolved_session_id] = [
                ResearchEventEnvelope(
                    event_id="evt-000001",
                    sequence=1,
                    timestamp="2026-03-29T00:00:00Z",
                    event_type="research.clarification.requested",
                    session_id=resolved_session_id,
                    phase="planner",
                    namespace="main",
                    payload=plan_result.clarification_request.model_dump(mode="json"),
                )
            ]
            self.artifacts[resolved_session_id] = [
                ResearchArtifactRead(
                    artifact_key="clarification_request",
                    content_json=plan_result.clarification_request.model_dump(mode="json"),
                )
            ]
            return session, plan_result

        if plan_result.plan_snapshot is not None:
            plan_snapshot = plan_result.plan_snapshot
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
        return session, plan_result

    async def submit_clarification(
        self,
        *,
        session: ResearchSession,
        answer: str,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        if session.status != ResearchSessionStatus.CLARIFYING:
            raise ValueError("clarification only allowed for clarifying session")
        effective_question = f"{session.question} {answer}".strip()
        plan_result = await self._planner.build_plan(
            ResearchSessionCreateRequest(question=effective_question)
        )
        session.status = plan_result.next_status
        self.event_envelopes[session.id].append(
            ResearchEventEnvelope(
                event_id="evt-000002",
                sequence=2,
                timestamp="2026-03-29T00:00:30Z",
                event_type="research.clarification.submitted",
                session_id=session.id,
                phase="planner",
                namespace="main",
                payload={"answer": answer},
            )
        )
        if plan_result.clarification_request is not None:
            self.event_envelopes[session.id].append(
                ResearchEventEnvelope(
                    event_id="evt-000003",
                    sequence=3,
                    timestamp="2026-03-29T00:01:00Z",
                    event_type="research.clarification.requested",
                    session_id=session.id,
                    phase="planner",
                    namespace="main",
                    payload=plan_result.clarification_request.model_dump(mode="json"),
                )
            )
            self.artifacts[session.id] = [
                ResearchArtifactRead(
                    artifact_key="clarification_request",
                    content_json=plan_result.clarification_request.model_dump(mode="json"),
                )
            ]
            return session, plan_result

        if plan_result.plan_snapshot is not None:
            plan_snapshot = plan_result.plan_snapshot
            self.plan_snapshots[session.id] = plan_snapshot
            self.event_envelopes[session.id].append(
                ResearchEventEnvelope(
                    event_id="evt-000003",
                    sequence=3,
                    timestamp="2026-03-29T00:01:00Z",
                    event_type="research.plan.created",
                    session_id=session.id,
                    phase="planner",
                    namespace="main",
                    payload={"question": effective_question},
                )
            )
            self.artifacts[session.id] = [
                ResearchArtifactRead(
                    artifact_key="plan_snapshot",
                    content_json=plan_snapshot.model_dump(mode="json"),
                )
            ]
        return session, plan_result

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        return self.sessions[session_id]

    def read_plan_snapshot(self, session: ResearchSession) -> ResearchPlanSnapshot:
        return self.plan_snapshots[session.id]

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

    def build_artifacts_response(self, session: ResearchSession):
        return {
            "session_id": str(session.id),
            "items": [item.model_dump(mode="json") for item in self.artifacts[session.id]],
        }


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
    assert "/research/sessions/{session_id}/clarification" in route_paths
    assert "/research/sessions/{session_id}/stream" in route_paths
    assert "/research/sessions/{session_id}/interrupt" in route_paths
    assert "/research/sessions/{session_id}/resume" in route_paths
    assert "/research/sessions/{session_id}/artifacts" in route_paths
    assert "/research/sessions/{session_id}/confirm-plan" not in route_paths
    assert not any(path.startswith("/research/runs") for path in route_paths)


def test_research_stream_cors_preflight_allows_last_event_id_header() -> None:
    client = TestClient(main_app)

    try:
        response = client.options(
            "/api/v1/research/sessions/31144cbe-5a61-4ff7-a624-f311f5f1cfba/stream"
            "?resume_from_event_id=evt-000001-bb536056",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Last-Event-ID",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    allow_headers = {
        item.strip().lower()
        for item in response.headers["access-control-allow-headers"].split(",")
    }
    assert "last-event-id" in allow_headers


def test_create_session_returns_queued_plan_snapshot_and_dispatches_immediately() -> None:
    service = _FakeResearchService(
        planner=ResearchPlanner(scoper=_SequenceScoper([_build_plan_snapshot("给出 research API 当前端点集合")]))
    )
    db = _FakeAsyncSession()
    dispatched: list[str] = []

    with _build_test_client(service=service, db=db, dispatched=dispatched) as client:
        response = client.post(
            "/api/v1/research/sessions",
            json={"question": "给出 research API 当前端点集合"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == ResearchSessionStatus.QUEUED.value
    assert payload["plan_snapshot"]["research_brief"].startswith("围绕“给出 research API 当前端点集合”")
    assert dispatched == [payload["session_id"]]
    assert db.commit_calls == 1


def test_create_session_returns_clarifying_status_without_dispatch_for_unclear_prompt() -> None:
    service = _FakeResearchService(
        planner=ResearchPlanner(
            scoper=_SequenceScoper(
                [
                    ResearchClarificationRequest(
                        summary="当前问题过宽，需要先明确研究目标。",
                        questions=[
                            ResearchClarificationQuestion(
                                id="scope",
                                question="你更关注个人使用建议，还是团队落地方案？",
                                why_it_matters="目标不同会影响研究结构。",
                            )
                        ],
                    )
                ]
            )
        )
    )
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


def test_clarification_submit_transitions_to_queued_and_dispatches() -> None:
    service = _FakeResearchService(
        planner=ResearchPlanner(
            scoper=_SequenceScoper(
                [
                    ResearchClarificationRequest(
                        summary="先补充场景。",
                        questions=[
                            ResearchClarificationQuestion(
                                id="scope",
                                question="你更关注哪个具体场景？",
                                why_it_matters="需要场景才能规划。",
                            )
                        ],
                    ),
                    _build_plan_snapshot("帮我研究一下 AI 编程工具 关注 LangGraph StateGraph 入门与使用场景"),
                ]
            )
        )
    )
    db = _FakeAsyncSession()
    dispatched: list[str] = []

    with _build_test_client(service=service, db=db, dispatched=dispatched) as client:
        response = client.post(
            "/api/v1/research/sessions",
            json={"question": "帮我研究一下 AI 编程工具"},
        )
        session_id = response.json()["session_id"]

        submit_response = client.post(
            f"/api/v1/research/sessions/{session_id}/clarification",
            json={"answer": "关注 LangGraph StateGraph 入门与使用场景"},
        )

    assert submit_response.status_code == 200
    payload = submit_response.json()
    assert payload["status"] == ResearchSessionStatus.QUEUED.value
    assert payload["plan_snapshot"]["research_brief"].startswith("围绕“帮我研究一下 AI 编程工具")
    assert dispatched == [session_id]


def test_stream_interrupt_resume_and_artifacts_flow_without_confirm_plan() -> None:
    service = _FakeResearchService(
        planner=ResearchPlanner(scoper=_SequenceScoper([_build_plan_snapshot("确认 research 计划")]))
    )
    db = _FakeAsyncSession()
    dispatched: list[str] = []

    with _build_test_client(service=service, db=db, dispatched=dispatched) as client:
        create_response = client.post(
            "/api/v1/research/sessions",
            json={"question": "确认 research 计划"},
        )
        session_id = create_response.json()["session_id"]
        assert create_response.json()["status"] == ResearchSessionStatus.QUEUED.value
        assert dispatched == [session_id]

        with client.stream(
            "GET",
            f"/api/v1/research/sessions/{session_id}/stream",
            headers={"Last-Event-ID": "evt-000001"},
        ) as stream_response:
            stream_text = "".join(stream_response.iter_text())
        assert stream_response.status_code == 200
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

        artifacts_response = client.get(f"/api/v1/research/sessions/{session_id}/artifacts")
        assert artifacts_response.status_code == 200
        assert artifacts_response.json()["items"][0]["artifact_key"] == "plan_snapshot"

    assert db.commit_calls == 3
