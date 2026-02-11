from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_batch import (
    IngestionBatch,
    IngestionBatchDoc,
    IngestionBatchStatus,
    IngestionDocStatus,
    IngestionSourceType,
)
from app.schemas.ingestion_batches import BatchStatus, DocStatus
from app.services.ingestion_batch_service import DOC_CANCELED_ERROR_CODE, IngestionBatchService


def _make_service() -> IngestionBatchService:
    return IngestionBatchService(cast(AsyncSession, object()))


def _make_batch(*, status: IngestionBatchStatus = IngestionBatchStatus.PROCESSING) -> IngestionBatch:
    return IngestionBatch(
        id=uuid4(),
        kb_id=uuid4(),
        config_snapshot_id=uuid4(),
        config_version=1,
        status=status,
        started_at=datetime.now(timezone.utc),
    )


def _make_doc(
    *,
    batch: IngestionBatch,
    status: IngestionDocStatus,
    error_code: str | None = None,
    chunk_count: int = 0,
) -> IngestionBatchDoc:
    return IngestionBatchDoc(
        id=uuid4(),
        batch_id=batch.id,
        kb_id=batch.kb_id,
        config_snapshot_id=batch.config_snapshot_id,
        config_version=1,
        source_type=IngestionSourceType.TEXT,
        source_ref=None,
        title=None,
        fingerprint=str(uuid4()),
        status=status,
        error_code=error_code,
        error_message=None,
        retry_count=0,
        retryable=False,
        chunk_count=chunk_count,
    )


def test_ingestion_status_enums_are_two_state() -> None:
    assert {status.value for status in IngestionBatchStatus} == {"processing", "completed"}
    assert {status.value for status in BatchStatus} == {"processing", "completed"}
    assert {status.value for status in IngestionDocStatus} == {"processing", "completed"}
    assert {status.value for status in DocStatus} == {"processing", "completed"}


def test_doc_outcome_classification() -> None:
    service = _make_service()
    batch = _make_batch()

    succeeded_doc = _make_doc(batch=batch, status=IngestionDocStatus.COMPLETED, error_code=None)
    failed_doc = _make_doc(batch=batch, status=IngestionDocStatus.COMPLETED, error_code="DOC_PROCESSING_ERROR")
    canceled_doc = _make_doc(
        batch=batch,
        status=IngestionDocStatus.COMPLETED,
        error_code=DOC_CANCELED_ERROR_CODE,
    )
    processing_doc_with_error = _make_doc(
        batch=batch,
        status=IngestionDocStatus.PROCESSING,
        error_code="TEMPORARY_ERROR",
    )

    assert service._is_doc_succeeded(succeeded_doc) is True
    assert service._is_doc_failed(failed_doc) is True
    assert service._is_doc_canceled(canceled_doc) is True

    assert service._is_doc_succeeded(processing_doc_with_error) is False
    assert service._is_doc_failed(processing_doc_with_error) is False
    assert service._is_doc_canceled(processing_doc_with_error) is False


@pytest.mark.asyncio
async def test_recalculate_batch_uses_two_state_lifecycle() -> None:
    service = _make_service()
    service._append_event = AsyncMock(return_value=None)  # type: ignore[method-assign]
    service._apply_readiness = AsyncMock(return_value=None)  # type: ignore[method-assign]

    batch = _make_batch(status=IngestionBatchStatus.PROCESSING)
    processing_doc = _make_doc(
        batch=batch,
        status=IngestionDocStatus.PROCESSING,
        error_code="TEMP_RETRY_ERROR",
    )
    succeeded_doc = _make_doc(
        batch=batch,
        status=IngestionDocStatus.COMPLETED,
        error_code=None,
        chunk_count=3,
    )
    failed_doc = _make_doc(
        batch=batch,
        status=IngestionDocStatus.COMPLETED,
        error_code="DOC_PROCESSING_ERROR",
    )
    batch.docs = [processing_doc, succeeded_doc, failed_doc]

    await service._recalculate_batch(batch, reason="first_pass")

    assert batch.status == IngestionBatchStatus.PROCESSING
    assert batch.succeeded_docs == 1
    assert batch.failed_docs == 1
    assert batch.canceled_docs == 0
    assert batch.succeeded_chunks == 3

    processing_doc.status = IngestionDocStatus.COMPLETED
    processing_doc.error_code = DOC_CANCELED_ERROR_CODE
    processing_doc.error_message = "批次已取消"

    await service._recalculate_batch(batch, reason="second_pass")

    assert batch.status == IngestionBatchStatus.COMPLETED
    assert batch.succeeded_docs == 1
    assert batch.failed_docs == 1
    assert batch.canceled_docs == 1
    assert batch.finished_at is not None
    service._apply_readiness.assert_awaited_once()
