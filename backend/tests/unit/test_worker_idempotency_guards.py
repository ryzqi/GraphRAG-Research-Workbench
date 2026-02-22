from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.models.agent_run import AgentRunStatus
from app.models.export_job import ExportStatus
from app.models.index_rebuild_job import IndexRebuildStatus
from app.worker.tasks import export as export_task
from app.worker.tasks import index_rebuild as rebuild_task
from app.worker.tasks import research as research_task


@dataclass
class _DummyRecord:
    status: object


class _FakeSession:
    def __init__(self, record: _DummyRecord) -> None:
        self._record = record
        self.commit_calls = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, _model, _id):  # noqa: ANN001
        return self._record

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSession:
        return self._session


def _fake_managed_resources(session: _FakeSession):
    @asynccontextmanager
    async def _manager(**_kwargs):
        yield SimpleNamespace(
            sessionmaker=_FakeSessionFactory(session),
            http_client=None,
            milvus=None,
        )

    return _manager


@pytest.mark.asyncio
async def test_export_task_skips_terminal_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _DummyRecord(status=ExportStatus.SUCCEEDED)
    session = _FakeSession(job)

    monkeypatch.setattr(export_task, "managed_task_resources", _fake_managed_resources(session))
    monkeypatch.setattr(export_task, "get_settings", lambda: SimpleNamespace(minio_bucket_exports="exports"))

    await export_task._run_export(
        export_id=str(uuid.uuid4()),
        export_type="chat",
        run_id=str(uuid.uuid4()),
    )

    assert session.commit_calls == 0
    assert job.status == ExportStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_index_rebuild_task_skips_terminal_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _DummyRecord(status=IndexRebuildStatus.SUCCEEDED)
    session = _FakeSession(job)

    monkeypatch.setattr(rebuild_task, "managed_task_resources", _fake_managed_resources(session))
    monkeypatch.setattr(rebuild_task, "get_settings", lambda: SimpleNamespace())

    await rebuild_task._run_index_rebuild_job(str(uuid.uuid4()))

    assert session.commit_calls == 0
    assert job.status == IndexRebuildStatus.SUCCEEDED


def test_research_task_allows_only_running_status() -> None:
    assert research_task._should_skip_run_status(AgentRunStatus.RUNNING) is False
    assert research_task._should_skip_run_status(AgentRunStatus.SUCCEEDED) is True
    assert research_task._should_skip_run_status(AgentRunStatus.FAILED) is True
    assert research_task._should_skip_run_status(AgentRunStatus.CANCELED) is True
