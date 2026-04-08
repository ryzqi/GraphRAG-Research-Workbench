from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.research import start_research_session
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
)
from app.services.queue_health_service import _build_queue_states
from app.services.research_service import ResearchService


class _RecordingDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.commits += 1


class _RecordingEventStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, **kwargs: object) -> None:
        self.events.append(kwargs)


class _EndpointResearchService:
    def __init__(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> None:
        self._session = session
        self._plan_snapshot = plan_snapshot

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        assert session_id == self._session.id
        return self._session

    async def start_session(self, *, session: ResearchSession) -> ResearchSession:
        assert session is self._session
        session.status = ResearchSessionStatus.QUEUED
        return session

    def read_plan_snapshot(self, session: ResearchSession) -> ResearchPlanSnapshot:
        assert session is self._session
        return self._plan_snapshot


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="brief",
        complexity=ResearchComplexity.SIMPLE,
        summary="summary",
        subtasks=[],
        target_sources=[ResearchSourceTarget.WEB],
        budget_guidance="budget",
    )


@pytest.mark.asyncio
async def test_start_endpoint_no_longer_calls_request_dispatcher() -> None:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="question",
        status=ResearchSessionStatus.PLAN_READY,
    )
    plan_snapshot = _build_plan_snapshot()
    service = _EndpointResearchService(session=session, plan_snapshot=plan_snapshot)
    db = _RecordingDb()

    def _unexpected_dispatch(_: str) -> None:
        raise AssertionError("request-level dispatcher should not be called")

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                research_service_factory=lambda **_: service,
                research_dispatcher=_unexpected_dispatch,
            )
        )
    )

    accepted = await start_research_session(
        session_id=session.id,
        db=db,
        request=request,
    )

    assert accepted.session_id == session.id
    assert accepted.status == ResearchSessionStatus.QUEUED
    assert accepted.plan_snapshot == plan_snapshot
    assert db.commits == 1


@pytest.mark.asyncio
async def test_start_session_creates_pending_research_outbox_row() -> None:
    db = _RecordingDb()
    event_store = _RecordingEventStore()
    service = ResearchService(
        db=db,  # type: ignore[arg-type]
        planner=SimpleNamespace(),
        runtime_runner=SimpleNamespace(),
        finalizer=SimpleNamespace(),
        event_store=event_store,  # type: ignore[arg-type]
    )
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-2",
        question="question",
        status=ResearchSessionStatus.PLAN_READY,
    )

    result = await service.start_session(session=session)

    assert result.status == ResearchSessionStatus.QUEUED
    assert len(db.added) == 1
    outbox = db.added[0]
    assert getattr(outbox, "session_id", None) == session.id
    assert getattr(outbox, "task_name", None) == "app.worker.tasks.research.run_research_session"
    assert getattr(getattr(outbox, "status", None), "value", None) == "pending"


def test_queue_health_marks_research_queue_as_required() -> None:
    states = _build_queue_states(consumer_counts={}, queue_lengths={})

    assert "research" in states
    assert states["research"].required is True
    assert states["research"].healthy is False
