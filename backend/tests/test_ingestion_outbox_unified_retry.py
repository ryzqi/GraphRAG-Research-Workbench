from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.ingestion_batch import IngestionDocStatus
from app.models.ingestion_task_outbox import IngestionTaskOutboxStatus
from app.services import ingestion_batch_service_status as ingestion_status
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.ingestion_batch_service_contracts import AUTO_RETRY_DELAYS


def _must_get_status(enum_cls: type, name: str):
    status = getattr(enum_cls, name, None)
    assert status is not None, f"{enum_cls.__name__}.{name} must exist"
    return status


def _make_doc(*, status, retry_count: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        batch_id=uuid4(),
        status=status,
        error_code=None,
        error_message=None,
        retry_count=retry_count,
        retryable=True,
        chunk_count=0,
        context_failed_chunks=None,
    )


def _make_outbox(*, status):
    return SimpleNamespace(
        status=status,
        attempts=1,
        max_attempts=20,
        next_retry_at=None,
        dispatched_at=datetime.now(timezone.utc),
        last_error="previous-error",
    )


class _FakeStatusService:
    def __init__(self) -> None:
        self._append_event = AsyncMock()

    async def _set_doc_status(self, doc, new_status, *, reason: str) -> None:
        await ingestion_status._set_doc_status(self, doc, new_status, reason=reason)


def test_outbox_status_model_exposes_succeeded_terminal_state() -> None:
    assert {member.value for member in IngestionTaskOutboxStatus} == {
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        "succeeded",
    }


@pytest.mark.asyncio
async def test_mark_doc_succeeded_marks_outbox_row_succeeded() -> None:
    service = _FakeStatusService()
    doc = _make_doc(status=_must_get_status(IngestionDocStatus, "PROCESSING"))
    outbox = _make_outbox(status=IngestionTaskOutboxStatus.DISPATCHED)

    await IngestionBatchService.mark_doc_succeeded(
        service,
        doc=doc,
        outbox=outbox,
        chunk_count=3,
        context_failed_chunks=[{"chunk_index": 1}],
    )

    assert doc.status == _must_get_status(IngestionDocStatus, "SUCCEEDED")
    assert outbox.status == _must_get_status(IngestionTaskOutboxStatus, "SUCCEEDED")
    assert outbox.next_retry_at is None
    assert outbox.dispatched_at is None
    assert outbox.last_error is None


@pytest.mark.asyncio
async def test_retryable_failure_requeues_existing_outbox_row_without_countdown() -> None:
    service = _FakeStatusService()
    doc = _make_doc(status=_must_get_status(IngestionDocStatus, "PROCESSING"))
    outbox = _make_outbox(status=IngestionTaskOutboxStatus.DISPATCHED)
    fixed_now = datetime(2026, 4, 14, 23, 10, tzinfo=timezone.utc)

    delay = await IngestionBatchService.mark_doc_failed(
        service,
        doc=doc,
        outbox=outbox,
        error_code="DOC_PARSE_EXCEPTION",
        error_message="parse failed",
        retryable=True,
        now=fixed_now,
    )

    assert delay is None
    assert doc.status == _must_get_status(IngestionDocStatus, "QUEUED")
    assert outbox.status == IngestionTaskOutboxStatus.FAILED
    assert outbox.last_error == "DOC_PARSE_EXCEPTION"
    assert outbox.dispatched_at is None
    assert outbox.next_retry_at == fixed_now + timedelta(seconds=AUTO_RETRY_DELAYS[0])
