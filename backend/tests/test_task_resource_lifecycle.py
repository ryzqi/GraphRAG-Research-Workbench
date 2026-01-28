from __future__ import annotations

import uuid

import pytest

from app.models.evaluation_run import EvaluationStatus
from app.worker.tasks import evaluation as evaluation_task
from app.worker import task_resources


class _DummyEvalRun:
    def __init__(self) -> None:
        self.status = EvaluationStatus.PENDING
        self.started_at = None
        self.finished_at = None
        self.summary = None
        self.error_message = None
        self.config = {"selected_kb_ids": [], "allow_external": False}
        self.dataset = {"questions": []}


class _DummySession:
    def __init__(self, eval_run: _DummyEvalRun) -> None:
        self._eval_run = eval_run

    async def get(self, _model, _id):
        return self._eval_run

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, _obj) -> None:
        return None


class _DummySessionmaker:
    def __init__(self, session: _DummySession) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


class _DummyRedis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _DummyHttpClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _DummyMilvus:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _DummyEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
async def test_evaluation_task_closes_redis_per_task(monkeypatch):
    eval_run = _DummyEvalRun()
    session = _DummySession(eval_run)
    engine = _DummyEngine()
    redis = _DummyRedis()
    http_client = _DummyHttpClient()
    milvus = _DummyMilvus()

    monkeypatch.setattr(task_resources, "create_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(
        task_resources,
        "create_sessionmaker",
        lambda engine: _DummySessionmaker(session),
    )
    monkeypatch.setattr(
        task_resources, "create_redis_client", lambda _settings: redis
    )
    monkeypatch.setattr(
        task_resources, "create_http_client", lambda _settings: http_client
    )
    monkeypatch.setattr(
        task_resources, "create_milvus_client", lambda: milvus
    )

    await evaluation_task._run_evaluation(eval_run_id=str(uuid.uuid4()))

    assert redis.closed is True
    assert http_client.closed is True
    assert milvus.closed is True
    assert engine.disposed is True
