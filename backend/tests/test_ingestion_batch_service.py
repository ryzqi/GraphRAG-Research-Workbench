from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.models.ingestion_batch import IngestionBatchStatus, IngestionDocStatus
from app.schemas.ingestion_batches import EntryErrorRead, ManifestSourceType
from app.services.ingestion_batch_service import MAX_MANIFEST_ENTRIES, IngestionBatchService
from app.services.ingestion_contract import ingestion_error


class _DummyDB:
    def __init__(self, *, kb: object | None = None) -> None:
        self._kb = kb
        self.committed = False
        self.rolled_back = False

    async def get(self, _model: object, _pk: object) -> object | None:
        return self._kb

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    def add(self, _obj: object) -> None:
        return None


@pytest.mark.asyncio
async def test_submit_manifest_rejects_entry_count_over_limit() -> None:
    service = IngestionBatchService(_DummyDB())

    with pytest.raises(AppError) as exc:
        await service.submit_manifest(
            kb_id=uuid.uuid4(),
            entries=[object()] * (MAX_MANIFEST_ENTRIES + 1),
        )

    assert exc.value.code == "MANIFEST_LIMIT_EXCEEDED"
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_submit_manifest_returns_400_when_all_entries_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id)
    service = IngestionBatchService(_DummyDB(kb=kb))

    async def _prepare_entries(**kwargs: object) -> list[object]:
        errors = kwargs["entry_errors"]
        errors.append(
            EntryErrorRead(
                entry_id="entry_1",
                source_type=ManifestSourceType.TEXT,
                code="TEXT_LENGTH_INVALID",
                message="文本长度不在允许范围内",
                retryable=False,
            )
        )
        return []

    async def _should_not_create(**_kwargs: object) -> tuple[object, list[object]]:
        raise AssertionError("batch should not be created when all entries fail")

    monkeypatch.setattr(service, "_prepare_entries", _prepare_entries)
    monkeypatch.setattr(service, "_create_batch_with_retry", _should_not_create)

    with pytest.raises(AppError) as exc:
        await service.submit_manifest(kb_id=kb_id, entries=[object()])

    assert exc.value.code == "MANIFEST_ALL_ENTRIES_FAILED"
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_mark_doc_failed_uses_fixed_auto_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    service = IngestionBatchService(_DummyDB())

    async def _set_doc_status(doc: object, new_status: IngestionDocStatus, *, reason: str) -> None:
        doc.status = new_status
        doc.last_reason = reason

    monkeypatch.setattr(service, "_set_doc_status", _set_doc_status)

    doc = SimpleNamespace(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        status=IngestionDocStatus.RUNNING,
        retry_count=1,
        retryable=True,
        error_code=None,
        error_message=None,
    )

    delay = await service.mark_doc_failed(
        doc=doc,
        error_code="URL_FETCH_EXCEPTION",
        error_message="timeout",
        retryable=True,
    )
    assert delay == 30
    assert doc.status == IngestionDocStatus.PENDING

    doc.status = IngestionDocStatus.RUNNING
    doc.retry_count = 2
    delay = await service.mark_doc_failed(
        doc=doc,
        error_code="URL_FETCH_EXCEPTION",
        error_message="timeout",
        retryable=True,
    )
    assert delay == 120
    assert doc.status == IngestionDocStatus.PENDING

    doc.status = IngestionDocStatus.RUNNING
    doc.retry_count = 3
    delay = await service.mark_doc_failed(
        doc=doc,
        error_code="URL_FETCH_EXCEPTION",
        error_message="timeout",
        retryable=True,
    )
    assert delay is None
    assert doc.status == IngestionDocStatus.FAILED


@pytest.mark.asyncio
async def test_recalculate_batch_applies_progress_formula_and_terminal_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IngestionBatchService(_DummyDB())

    async def _set_batch_status(batch: object, new_status: IngestionBatchStatus, *, reason: str) -> None:
        del reason
        batch.status = new_status

    readiness_called = False

    async def _apply_readiness(*, batch: object) -> None:
        nonlocal readiness_called
        del batch
        readiness_called = True

    monkeypatch.setattr(service, "_set_batch_status", _set_batch_status)
    monkeypatch.setattr(service, "_apply_readiness", _apply_readiness)

    docs = [
        SimpleNamespace(status=IngestionDocStatus.SUCCEEDED, chunk_count=3),
        SimpleNamespace(status=IngestionDocStatus.FAILED, chunk_count=0),
        SimpleNamespace(status=IngestionDocStatus.CANCELED, chunk_count=0),
        SimpleNamespace(status=IngestionDocStatus.SUCCEEDED, chunk_count=2),
    ]
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        status=IngestionBatchStatus.RUNNING,
        docs=docs,
        is_bootstrap=False,
        total_docs=0,
        succeeded_docs=0,
        failed_docs=0,
        canceled_docs=0,
        succeeded_chunks=0,
        progress_percent=0,
        error_summary=None,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )

    await service._recalculate_batch(batch, reason="unit_test")

    assert batch.total_docs == 4
    assert batch.succeeded_docs == 2
    assert batch.failed_docs == 1
    assert batch.canceled_docs == 1
    assert batch.succeeded_chunks == 5
    assert batch.progress_percent == 100
    assert batch.status == IngestionBatchStatus.PARTIAL_FAILED
    assert readiness_called is True


@pytest.mark.asyncio
async def test_retry_failed_docs_only_requeues_eligible_failed_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _DummyDB()
    service = IngestionBatchService(db)

    eligible = SimpleNamespace(
        id=uuid.uuid4(),
        status=IngestionDocStatus.FAILED,
        retry_count=2,
        retryable=False,
        error_code="E",
        error_message="err",
    )
    over_limit = SimpleNamespace(
        id=uuid.uuid4(),
        status=IngestionDocStatus.FAILED,
        retry_count=5,
        retryable=False,
        error_code="E",
        error_message="err",
    )
    succeeded = SimpleNamespace(
        id=uuid.uuid4(),
        status=IngestionDocStatus.SUCCEEDED,
        retry_count=1,
        retryable=False,
        error_code=None,
        error_message=None,
    )
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        status=IngestionBatchStatus.PARTIAL_FAILED,
        docs=[eligible, over_limit, succeeded],
    )

    async def _get_batch_or_raise(*, batch_id: uuid.UUID, for_update: bool = False) -> object:
        del batch_id, for_update
        return batch

    async def _set_doc_status(doc: object, new_status: IngestionDocStatus, *, reason: str) -> None:
        del reason
        doc.status = new_status

    async def _recalculate_batch(_batch: object, *, reason: str) -> None:
        del reason
        _batch.status = IngestionBatchStatus.QUEUED

    queued_ids: list[uuid.UUID] = []

    monkeypatch.setattr(service, "_get_batch_or_raise", _get_batch_or_raise)
    monkeypatch.setattr(service, "_set_doc_status", _set_doc_status)
    monkeypatch.setattr(service, "_recalculate_batch", _recalculate_batch)
    monkeypatch.setattr(service, "_enqueue_docs", lambda ids: queued_ids.extend(ids))

    result = await service.retry_failed_docs(batch_id=batch.id)

    assert db.committed is True
    assert result.requeued_docs == 1
    assert result.ignored_docs == 2
    assert queued_ids == [eligible.id]
    assert eligible.status == IngestionDocStatus.PENDING
    assert eligible.retryable is True
    assert eligible.error_code is None
    assert eligible.error_message is None


@pytest.mark.asyncio
async def test_cancel_batch_rejects_terminal_status(monkeypatch: pytest.MonkeyPatch) -> None:
    service = IngestionBatchService(_DummyDB())
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        status=IngestionBatchStatus.SUCCEEDED,
        docs=[],
    )

    async def _get_batch_or_raise(*, batch_id: uuid.UUID, for_update: bool = False) -> object:
        del batch_id, for_update
        return batch

    monkeypatch.setattr(service, "_get_batch_or_raise", _get_batch_or_raise)

    with pytest.raises(AppError) as exc:
        await service.cancel_batch(batch_id=batch.id)

    assert exc.value.code == "BATCH_STATUS_CONFLICT"


def test_ingestion_error_contract_injects_retryable_and_message_key() -> None:
    err = ingestion_error("KB_BOOTSTRAP_CONFLICT")

    assert err.code == "KB_BOOTSTRAP_CONFLICT"
    assert err.status_code == 409
    assert err.details is not None
    assert err.details["retryable"] is True
    assert err.details["message_key"] == "kb.bootstrap.conflict"
