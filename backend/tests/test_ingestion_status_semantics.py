from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.ingestion_batch import IngestionBatchStatus, IngestionDocStatus
from app.schemas.ingestion_batches import BatchStatus, DocStatus
from app.services import ingestion_batch_service_status as ingestion_status
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.ingestion_batch_service_contracts import DOC_CANCELED_ERROR_CODE


def _enum_values(enum_cls: type) -> set[str]:
    return {member.value for member in enum_cls}


def _must_get_status(enum_cls: type, name: str):
    status = getattr(enum_cls, name, None)
    assert status is not None, f"{enum_cls.__name__}.{name} must exist"
    return status


def _make_doc(*, batch_id, status, chunk_count: int = 0):
    return SimpleNamespace(
        id=uuid4(),
        batch_id=batch_id,
        status=status,
        error_code=None,
        error_message=None,
        retry_count=1,
        retryable=True,
        chunk_count=chunk_count,
        context_failed_chunks=None,
    )


def _make_batch(*, status, docs):
    return SimpleNamespace(
        id=uuid4(),
        kb_id=uuid4(),
        status=status,
        docs=list(docs),
        total_docs=0,
        succeeded_docs=0,
        failed_docs=0,
        canceled_docs=0,
        succeeded_chunks=0,
        error_summary=None,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        is_bootstrap=False,
    )


class _FakeDb:
    def __init__(self) -> None:
        self.commit = AsyncMock()


class _FakeStatusService:
    def __init__(self, *, batch=None) -> None:
        self._append_event = AsyncMock()
        self._apply_readiness = AsyncMock()
        self._db = _FakeDb()
        self._batch = batch

    def _is_doc_succeeded(self, doc):
        return ingestion_status._is_doc_succeeded(doc)

    def _is_doc_failed(self, doc):
        return ingestion_status._is_doc_failed(doc)

    def _is_doc_canceled(self, doc):
        return ingestion_status._is_doc_canceled(doc)

    async def _set_doc_status(self, doc, new_status, *, reason: str) -> None:
        await ingestion_status._set_doc_status(
            self,
            doc,
            new_status,
            reason=reason,
        )

    async def _set_batch_status(self, batch, new_status, *, reason: str) -> None:
        await ingestion_status._set_batch_status(
            self,
            batch,
            new_status,
            reason=reason,
        )

    async def _recalculate_batch(self, batch, *, reason: str) -> None:
        await ingestion_status._recalculate_batch(self, batch, reason=reason)

    async def _get_batch_or_raise(
        self,
        *,
        batch_id,
        for_update: bool = False,
        populate_existing: bool = False,
    ):
        del batch_id, for_update, populate_existing
        assert self._batch is not None
        return self._batch


def test_explicit_status_enums_are_exposed_by_models_and_schemas() -> None:
    assert _enum_values(IngestionDocStatus) == {
        "queued",
        "processing",
        "succeeded",
        "failed",
        "canceled",
    }
    assert _enum_values(DocStatus) == {
        "queued",
        "processing",
        "succeeded",
        "failed",
        "canceled",
    }
    assert _enum_values(IngestionBatchStatus) == {
        "queued",
        "processing",
        "completed",
        "failed",
        "canceled",
    }
    assert _enum_values(BatchStatus) == {
        "queued",
        "processing",
        "completed",
        "failed",
        "canceled",
    }


@pytest.mark.asyncio
async def test_mark_doc_succeeded_sets_explicit_succeeded_status() -> None:
    batch_id = uuid4()
    doc = _make_doc(
        batch_id=batch_id,
        status=_must_get_status(IngestionDocStatus, "PROCESSING"),
    )
    service = _FakeStatusService()

    await IngestionBatchService.mark_doc_succeeded(
        service,
        doc=doc,
        chunk_count=3,
        context_failed_chunks=[{"chunk_index": 2}],
    )

    assert doc.status == _must_get_status(IngestionDocStatus, "SUCCEEDED")
    assert doc.chunk_count == 3
    assert doc.retryable is False
    assert doc.error_code is None
    assert doc.error_message is None


@pytest.mark.asyncio
async def test_mark_doc_failed_without_retry_sets_explicit_failed_status() -> None:
    batch_id = uuid4()
    doc = _make_doc(
        batch_id=batch_id,
        status=_must_get_status(IngestionDocStatus, "PROCESSING"),
    )
    service = _FakeStatusService()

    delay = await IngestionBatchService.mark_doc_failed(
        service,
        doc=doc,
        error_code="DOC_PARSE_EXCEPTION",
        error_message="parse failed",
        retryable=False,
    )

    assert delay is None
    assert doc.status == _must_get_status(IngestionDocStatus, "FAILED")
    assert doc.retryable is False
    assert doc.error_code == "DOC_PARSE_EXCEPTION"
    assert doc.error_message == "parse failed"


@pytest.mark.asyncio
async def test_cancel_batch_marks_processing_docs_canceled() -> None:
    processing_status = _must_get_status(IngestionDocStatus, "PROCESSING")
    canceled_doc_status = _must_get_status(IngestionDocStatus, "CANCELED")
    processing_batch_status = _must_get_status(IngestionBatchStatus, "PROCESSING")
    canceled_batch_status = _must_get_status(BatchStatus, "CANCELED")

    batch = _make_batch(status=processing_batch_status, docs=[])
    doc = _make_doc(batch_id=batch.id, status=processing_status)
    batch.docs = [doc]
    service = _FakeStatusService(batch=batch)

    response = await IngestionBatchService.cancel_batch(service, batch_id=batch.id)

    assert doc.status == canceled_doc_status
    assert doc.error_code == DOC_CANCELED_ERROR_CODE
    assert response.status == canceled_batch_status
    assert response.canceled_docs == 1


@pytest.mark.asyncio
async def test_recalculate_batch_aggregates_explicit_terminal_statuses() -> None:
    succeeded_status = _must_get_status(IngestionDocStatus, "SUCCEEDED")
    failed_status = _must_get_status(IngestionDocStatus, "FAILED")
    canceled_status = _must_get_status(IngestionDocStatus, "CANCELED")
    failed_batch_status = _must_get_status(IngestionBatchStatus, "FAILED")

    batch = _make_batch(
        status=_must_get_status(IngestionBatchStatus, "PROCESSING"),
        docs=[],
    )
    batch.docs = [
        _make_doc(batch_id=batch.id, status=succeeded_status, chunk_count=4),
        _make_doc(batch_id=batch.id, status=failed_status),
        _make_doc(batch_id=batch.id, status=canceled_status),
    ]
    service = _FakeStatusService()

    await ingestion_status._recalculate_batch(service, batch, reason="status_rollup")

    assert batch.succeeded_docs == 1
    assert batch.failed_docs == 1
    assert batch.canceled_docs == 1
    assert batch.succeeded_chunks == 4
    assert batch.status == failed_batch_status
