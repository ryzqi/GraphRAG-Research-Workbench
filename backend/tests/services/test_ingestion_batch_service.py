from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ingestion_batch_service import IngestionBatchService


@pytest.mark.asyncio
async def test_recalculate_batch_for_doc_refreshes_cached_batch_snapshot() -> None:
    service = IngestionBatchService(db=AsyncMock())
    doc = SimpleNamespace(batch_id=uuid.uuid4())
    batch = object()
    get_batch = AsyncMock(return_value=batch)
    recalculate = AsyncMock()
    service._get_batch_or_raise = get_batch  # type: ignore[attr-defined]
    service._recalculate_batch = recalculate  # type: ignore[attr-defined]

    await service.recalculate_batch_for_doc(doc=doc, reason="doc_succeeded")

    get_batch.assert_awaited_once_with(
        batch_id=doc.batch_id,
        for_update=True,
        populate_existing=True,
    )
    recalculate.assert_awaited_once_with(batch, reason="doc_succeeded")
