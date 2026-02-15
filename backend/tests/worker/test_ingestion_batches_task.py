from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.errors import AppError
from app.worker.tasks.ingestion_batches import _finalize_doc_on_app_error


@pytest.mark.asyncio
async def test_finalize_doc_on_app_error_marks_processing_doc_failed() -> None:
    doc_id = uuid.uuid4()
    doc = SimpleNamespace(status=SimpleNamespace(value="processing"))
    service = SimpleNamespace(
        rollback=AsyncMock(),
        get_doc=AsyncMock(return_value=doc),
        mark_doc_failed=AsyncMock(return_value=None),
        recalculate_batch_for_doc=AsyncMock(),
        commit=AsyncMock(),
    )
    error = AppError(code="DOC_PARSE_EXCEPTION", message="parse failed")

    await _finalize_doc_on_app_error(service=service, doc_id=doc_id, error=error)

    service.rollback.assert_awaited_once()
    service.get_doc.assert_awaited_once_with(doc_id=doc_id, for_update=True)
    service.mark_doc_failed.assert_awaited_once_with(
        doc=doc,
        error_code="DOC_PARSE_EXCEPTION",
        error_message="parse failed",
        retryable=False,
    )
    service.recalculate_batch_for_doc.assert_awaited_once_with(
        doc=doc,
        reason="doc_failed_app_error",
    )
    service.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_doc_on_app_error_skips_completed_doc() -> None:
    doc_id = uuid.uuid4()
    doc = SimpleNamespace(status=SimpleNamespace(value="completed"))
    service = SimpleNamespace(
        rollback=AsyncMock(),
        get_doc=AsyncMock(return_value=doc),
        mark_doc_failed=AsyncMock(return_value=None),
        recalculate_batch_for_doc=AsyncMock(),
        commit=AsyncMock(),
    )
    error = AppError(code="DOC_PARSE_EXCEPTION", message="parse failed")

    await _finalize_doc_on_app_error(service=service, doc_id=doc_id, error=error)

    service.rollback.assert_awaited_once()
    service.get_doc.assert_awaited_once_with(doc_id=doc_id, for_update=True)
    service.mark_doc_failed.assert_not_awaited()
    service.recalculate_batch_for_doc.assert_not_awaited()
    service.commit.assert_not_awaited()
