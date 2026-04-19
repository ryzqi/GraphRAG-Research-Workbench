import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import research as research_endpoint
from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
)
from app.worker.celery_app import celery_app


def test_beat_schedule_frequency_reduced() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["ingestion-outbox-dispatcher"]["schedule"].total_seconds() >= 20
    assert schedule["research-outbox-dispatcher"]["schedule"].total_seconds() >= 30
    assert schedule["index-rebuild-outbox-dispatcher"]["schedule"].total_seconds() >= 30
    assert schedule["bootstrap-watchdog"]["schedule"].total_seconds() >= 30
    assert schedule["ingestion-doc-watchdog"]["schedule"].total_seconds() >= 60


@pytest.mark.asyncio
async def test_start_research_session_triggers_outbox_dispatch_after_commit() -> None:
    session_id = uuid.uuid4()
    calls: list[str] = []
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="brief",
        complexity=ResearchComplexity.SIMPLE,
        summary="summary",
        target_sources=[ResearchSourceTarget.WEB],
    )
    session = SimpleNamespace(
        id=session_id,
        question="question",
        status="queued",
    )

    class _FakeDb:
        async def commit(self) -> None:
            calls.append("commit")

    class _FakeService:
        async def get_session(self, target_session_id: uuid.UUID):
            calls.append(f"get:{target_session_id}")
            return session

        async def start_session(self, *, session):
            calls.append("start")
            return session

        def read_plan_snapshot(self, target_session):
            calls.append("read_plan")
            assert target_session is session
            return plan_snapshot

        def trigger_outbox_dispatch(self) -> None:
            calls.append("trigger")

    response = await research_endpoint.start_research_session(
        session_id=session_id,
        db=_FakeDb(),
        service=_FakeService(),
    )

    assert calls == [f"get:{session_id}", "start", "commit", "trigger", "read_plan"]
    assert response.session_id == session_id
