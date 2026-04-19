from __future__ import annotations

from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace
import uuid

import pytest

from app.core.settings import Settings
from app.models.research_session import ResearchSessionStatus
from app.worker.tasks import research as research_task


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class _SessionContext(AbstractAsyncContextManager):
    def __init__(self, session: SimpleNamespace) -> None:
        self._session = session

    async def __aenter__(self) -> SimpleNamespace:
        self._session.closed = False
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._session.closed = True
        return False


class _SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[SimpleNamespace] = []

    def __call__(self) -> _SessionContext:
        session = SimpleNamespace(
            name=f"session_{len(self.sessions)}",
            closed=False,
            commit_calls=0,
            rollback_calls=0,
        )

        async def _commit() -> None:
            session.commit_calls += 1

        async def _rollback() -> None:
            session.rollback_calls += 1

        session.commit = _commit
        session.rollback = _rollback
        self.sessions.append(session)
        return _SessionContext(session)


@pytest.mark.asyncio
async def test_run_research_session_closes_bootstrap_session_before_execute_session(
    monkeypatch,
) -> None:
    settings = _make_settings()
    session_id = uuid.uuid4()
    session_factory = _SessionFactory()
    runtime_runner = object()
    expected_plan_snapshot = object()
    research_session = SimpleNamespace(
        id=session_id,
        status=ResearchSessionStatus.QUEUED,
        runtime_phase=None,
    )

    @asynccontextmanager
    async def _fake_managed_task_resources(**_kwargs):
        yield SimpleNamespace(sessionmaker=session_factory)

    class _FakeResearchService:
        def __init__(self, *, db, runtime_runner, sessionmaker=None) -> None:  # noqa: ANN001
            self._db = db
            self._runtime_runner = runtime_runner
            self._sessionmaker = sessionmaker

        async def get_session(self, requested_id: uuid.UUID):  # noqa: ANN201
            assert requested_id == session_id
            return research_session

        def read_plan_snapshot(self, session) -> object:  # noqa: ANN001
            assert session is research_session
            return expected_plan_snapshot

        async def execute_session(self, *, session, plan_snapshot) -> None:  # noqa: ANN001
            assert session is research_session
            assert plan_snapshot is expected_plan_snapshot
            assert self._sessionmaker is session_factory
            assert session_factory.sessions[0].closed is True

        async def fail_session(self, **_kwargs) -> None:
            raise AssertionError("success path should not call fail_session")

    async def _fake_get_cached_runner(**_kwargs):
        return runtime_runner

    monkeypatch.setattr(research_task, "get_settings", lambda: settings)
    monkeypatch.setattr(
        research_task,
        "managed_task_resources",
        _fake_managed_task_resources,
    )
    monkeypatch.setattr(
        research_task,
        "get_cached_runner",
        _fake_get_cached_runner,
    )
    monkeypatch.setattr(
        research_task,
        "build_research_service",
        lambda **kwargs: _FakeResearchService(**kwargs),
    )

    await research_task._run_research_session(str(session_id))

    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


@pytest.mark.asyncio
async def test_run_research_session_uses_fresh_session_for_failure_recovery(
    monkeypatch,
) -> None:
    settings = _make_settings()
    session_id = uuid.uuid4()
    session_factory = _SessionFactory()
    runtime_runner = object()
    expected_plan_snapshot = object()
    research_session = SimpleNamespace(
        id=session_id,
        status=ResearchSessionStatus.QUEUED,
        runtime_phase="runtime",
    )
    build_calls: list[SimpleNamespace] = []

    @asynccontextmanager
    async def _fake_managed_task_resources(**_kwargs):
        yield SimpleNamespace(sessionmaker=session_factory)

    class _FakeResearchService:
        def __init__(self, *, db, runtime_runner, sessionmaker=None) -> None:  # noqa: ANN001
            self._db = db
            self._runtime_runner = runtime_runner
            self._sessionmaker = sessionmaker
            build_calls.append(db)

        async def get_session(self, requested_id: uuid.UUID):  # noqa: ANN201
            assert requested_id == session_id
            return research_session

        def read_plan_snapshot(self, session) -> object:  # noqa: ANN001
            assert session is research_session
            return expected_plan_snapshot

        async def execute_session(self, *, session, plan_snapshot) -> None:  # noqa: ANN001
            assert session is research_session
            assert plan_snapshot is expected_plan_snapshot
            assert self._sessionmaker is session_factory
            assert session_factory.sessions[0].closed is True
            raise RuntimeError("execute boom")

        async def fail_session(self, *, session, exc, phase: str) -> None:  # noqa: ANN001
            assert session is research_session
            assert str(exc) == "execute boom"
            assert phase == "runtime"
            assert self._sessionmaker is session_factory
            assert len(session_factory.sessions) >= 2
            assert self._db is session_factory.sessions[1]

    async def _fake_get_cached_runner(**_kwargs):
        return runtime_runner

    monkeypatch.setattr(research_task, "get_settings", lambda: settings)
    monkeypatch.setattr(
        research_task,
        "managed_task_resources",
        _fake_managed_task_resources,
    )
    monkeypatch.setattr(
        research_task,
        "get_cached_runner",
        _fake_get_cached_runner,
    )
    monkeypatch.setattr(
        research_task,
        "build_research_service",
        lambda **kwargs: _FakeResearchService(**kwargs),
    )

    await research_task._run_research_session(str(session_id))

    assert build_calls[0] is session_factory.sessions[0]
    assert build_calls[1] is session_factory.sessions[1]
    assert session_factory.sessions[0].closed is True
    assert session_factory.sessions[1].closed is True
