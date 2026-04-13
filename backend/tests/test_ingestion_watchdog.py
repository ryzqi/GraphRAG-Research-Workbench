from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.ingestion_batch import IngestionDocStatus
from app.models.ingestion_task_outbox import IngestionTaskOutboxStatus
import app.worker.tasks.ingestion_watchdog as ingestion_watchdog


class _FakeExecuteResult:
    def __init__(self, *, rows=None, scalar=None) -> None:
        self._rows = list(rows or [])
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    def __init__(self, *, doc_id, outbox) -> None:
        self._results = [
            _FakeExecuteResult(rows=[(doc_id,)]),
            _FakeExecuteResult(scalar=outbox),
        ]
        self.commit_called = False
        self.rollback_called = False

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("unexpected execute call")
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commit_called = True

    async def rollback(self) -> None:
        self.rollback_called = True


class _FakeService:
    current_doc = None
    instances: list["_FakeService"] = []

    def __init__(self, _session) -> None:
        self.failed_calls: list[dict[str, object]] = []
        self.recalculate_calls: list[str] = []
        type(self).instances.append(self)

    async def get_doc(self, *, doc_id, for_update: bool):
        del doc_id, for_update
        return type(self).current_doc

    async def mark_doc_failed(
        self,
        *,
        doc,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> None:
        self.failed_calls.append(
            {
                "doc": doc,
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
            }
        )
        return None

    async def recalculate_batch_for_doc(self, *, doc, reason: str) -> None:
        del doc
        self.recalculate_calls.append(reason)


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, *, doc, outbox) -> _FakeSession:
    session = _FakeSession(doc_id=doc.id, outbox=outbox)

    @asynccontextmanager
    async def _session_scope():
        yield session

    @asynccontextmanager
    async def _managed_task_resources(*, settings, with_engine: bool):
        del settings, with_engine
        yield SimpleNamespace(sessionmaker=lambda: _session_scope())

    _FakeService.current_doc = doc
    _FakeService.instances = []

    monkeypatch.setattr(
        ingestion_watchdog,
        "get_settings",
        lambda: SimpleNamespace(ingestion_doc_queue_timeout_seconds=600),
    )
    monkeypatch.setattr(
        ingestion_watchdog,
        "managed_task_resources",
        _managed_task_resources,
    )
    monkeypatch.setattr(
        ingestion_watchdog,
        "IngestionBatchService",
        _FakeService,
    )
    return session


@pytest.mark.asyncio
async def test_watchdog_skips_bootstrap_batch_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = SimpleNamespace(
        id=uuid4(),
        status=IngestionDocStatus.PROCESSING,
        batch=SimpleNamespace(is_bootstrap=True),
    )
    outbox = SimpleNamespace(
        attempts=0,
        max_attempts=0,
        status=None,
        last_error=None,
        next_retry_at=None,
        dispatched_at=None,
    )
    session = _patch_runtime(monkeypatch, doc=doc, outbox=outbox)

    processed = await ingestion_watchdog._fail_stale_processing_docs(limit=10)

    assert processed == 0
    assert session.commit_called is True
    service = _FakeService.instances[0]
    assert service.failed_calls == []
    assert service.recalculate_calls == []
    assert outbox.status is None


@pytest.mark.asyncio
async def test_watchdog_still_fails_non_bootstrap_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = SimpleNamespace(
        id=uuid4(),
        status=IngestionDocStatus.PROCESSING,
        batch=SimpleNamespace(is_bootstrap=False),
    )
    outbox = SimpleNamespace(
        attempts=0,
        max_attempts=0,
        status=None,
        last_error=None,
        next_retry_at=None,
        dispatched_at=None,
    )
    session = _patch_runtime(monkeypatch, doc=doc, outbox=outbox)

    processed = await ingestion_watchdog._fail_stale_processing_docs(limit=10)

    assert processed == 1
    assert session.commit_called is True
    service = _FakeService.instances[0]
    assert service.failed_calls == [
        {
            "doc": doc,
            "error_code": ingestion_watchdog.DOC_QUEUE_TIMEOUT_ERROR_CODE,
            "error_message": ingestion_watchdog.DOC_QUEUE_TIMEOUT_MESSAGE,
            "retryable": False,
        }
    ]
    assert service.recalculate_calls == ["doc_timeout_watchdog"]
    assert outbox.status == IngestionTaskOutboxStatus.FAILED
    assert outbox.last_error == ingestion_watchdog.DOC_QUEUE_TIMEOUT_ERROR_CODE
    assert outbox.next_retry_at is None
    assert outbox.dispatched_at is None
