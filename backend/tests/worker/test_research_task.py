from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.models.research_session import ResearchSessionStatus
from app.worker.tasks import research as research_task_module


class _FakeDbSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _SessionContext:
    def __init__(self, db: _FakeDbSession) -> None:
        self._db = db

    async def __aenter__(self) -> _FakeDbSession:
        return self._db

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _Sessionmaker:
    def __init__(self, db: _FakeDbSession) -> None:
        self._db = db

    def __call__(self) -> _SessionContext:
        return _SessionContext(self._db)


@pytest.mark.asyncio
async def test_run_research_session_builds_service_with_configured_runtime_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDbSession()
    settings = SimpleNamespace()
    http_client = object()
    redis = object()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id,
        status=ResearchSessionStatus.QUEUED,
        runtime_phase=None,
    )
    sentinel_runtime_runner = object()
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def _fake_managed_task_resources(**kwargs):  # type: ignore[no-untyped-def]
        captured["managed_task_resources_kwargs"] = kwargs
        yield SimpleNamespace(
            sessionmaker=_Sessionmaker(db),
            http_client=http_client,
            redis=redis,
        )

    async def _fake_build_runtime_runner(**kwargs):  # type: ignore[no-untyped-def]
        captured["runtime_runner_kwargs"] = kwargs
        return sentinel_runtime_runner

    class _FakeService:
        async def get_session(self, target_session_id):  # type: ignore[no-untyped-def]
            assert target_session_id == session_id
            return session

        def read_plan_snapshot(self, current_session):  # type: ignore[no-untyped-def]
            assert current_session is session
            return {"plan": "snapshot"}

        async def execute_session(self, *, session, plan_snapshot):  # type: ignore[no-untyped-def]
            captured["executed_session"] = session
            captured["executed_plan_snapshot"] = plan_snapshot

        async def fail_session(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("不应进入 fail_session")

    def _fake_build_research_service(*, db, runtime_runner=None):  # type: ignore[no-untyped-def]
        captured["build_research_service_db"] = db
        captured["build_research_service_runtime_runner"] = runtime_runner
        return _FakeService()

    monkeypatch.setattr(research_task_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        research_task_module,
        "managed_task_resources",
        _fake_managed_task_resources,
    )
    monkeypatch.setattr(
        research_task_module,
        "build_deep_research_runtime_runner",
        _fake_build_runtime_runner,
        raising=False,
    )
    monkeypatch.setattr(
        research_task_module,
        "build_research_service",
        _fake_build_research_service,
    )

    await research_task_module._run_research_session(str(session_id))

    assert captured["managed_task_resources_kwargs"] == {
        "settings": settings,
        "with_engine": True,
        "with_http": True,
        "with_redis": True,
        "with_milvus": False,
    }
    assert captured["build_research_service_runtime_runner"] is sentinel_runtime_runner
    assert captured["runtime_runner_kwargs"] == {
        "settings": settings,
        "http_client": http_client,
        "redis": redis,
    }
    assert captured["executed_session"] is session
    assert captured["executed_plan_snapshot"] == {"plan": "snapshot"}
    assert db.commit_calls == 1
    assert db.rollback_calls == 0
