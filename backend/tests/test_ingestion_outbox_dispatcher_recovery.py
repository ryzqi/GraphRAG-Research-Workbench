from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.ingestion_task_outbox import IngestionTaskOutboxStatus
from app.worker.tasks import ingestion_outbox_dispatcher as dispatcher


class _FakeScalars:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


@pytest.mark.asyncio
async def test_recover_stale_dispatched_rows_marks_rows_retryable() -> None:
    now = datetime.now(timezone.utc)
    stale_row = SimpleNamespace(
        id="outbox-1",
        batch_id="batch-1",
        doc_id="doc-1",
        status=IngestionTaskOutboxStatus.DISPATCHED,
        attempts=3,
        max_attempts=20,
        dispatched_at=now - timedelta(hours=2),
        next_retry_at=None,
        last_error=None,
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_FakeResult([stale_row]))

    recovered = await dispatcher._recover_stale_dispatched_rows(session=session, limit=5, now=now)

    assert recovered == 1
    assert stale_row.status == IngestionTaskOutboxStatus.FAILED
    assert stale_row.dispatched_at is None
    assert stale_row.next_retry_at == now
    assert stale_row.last_error is not None
    assert "stale" in stale_row.last_error
