"""Celery task that dispatches ingestion doc tasks from transactional outbox."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.settings import get_settings
from app.models.ingestion_task_outbox import (
    IngestionTaskOutbox,
    IngestionTaskOutboxStatus,
)
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources

logger = logging.getLogger(__name__)

DEFAULT_DISPATCH_BATCH_SIZE = 50
MAX_RETRY_BACKOFF_SECONDS = 600
RETRY_BASE_SECONDS = 5
MAX_ERROR_MESSAGE_LENGTH = 2000


def _compute_retry_delay_seconds(*, attempts: int) -> int:
    bounded_attempt = max(1, min(attempts, 10))
    return min(MAX_RETRY_BACKOFF_SECONDS, RETRY_BASE_SECONDS * (2 ** (bounded_attempt - 1)))


def _format_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:MAX_ERROR_MESSAGE_LENGTH]


async def _claim_due_outbox_rows(*, session, limit: int) -> list[IngestionTaskOutbox]:  # noqa: ANN001
    now = datetime.now(timezone.utc)
    stmt = (
        select(IngestionTaskOutbox)
        .where(
            IngestionTaskOutbox.status.in_(
                [IngestionTaskOutboxStatus.PENDING, IngestionTaskOutboxStatus.FAILED]
            ),
            or_(
                IngestionTaskOutbox.next_retry_at.is_(None),
                IngestionTaskOutbox.next_retry_at <= now,
            ),
            IngestionTaskOutbox.attempts < IngestionTaskOutbox.max_attempts,
        )
        .order_by(IngestionTaskOutbox.created_at.asc(), IngestionTaskOutbox.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = IngestionTaskOutboxStatus.DISPATCHING
    return rows


@celery_app.task(
    name="app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox"
)
def dispatch_ingestion_outbox(limit: int = DEFAULT_DISPATCH_BATCH_SIZE) -> None:
    asyncio.run(_dispatch_ingestion_outbox(limit=limit))


async def _dispatch_ingestion_outbox(*, limit: int = DEFAULT_DISPATCH_BATCH_SIZE) -> int:
    settings = get_settings()
    safe_limit = max(int(limit or DEFAULT_DISPATCH_BATCH_SIZE), 1)

    async with managed_task_resources(settings=settings, with_engine=True) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive guard
            return 0

        dispatched_rows = 0
        async with sessionmaker() as session:
            while True:
                rows = await _claim_due_outbox_rows(session=session, limit=safe_limit)
                if not rows:
                    await session.rollback()
                    break

                from app.worker.tasks.ingestion_batches import run_ingestion_batch_doc

                for row in rows:
                    now = datetime.now(timezone.utc)
                    row.attempts += 1
                    try:
                        run_ingestion_batch_doc.delay(str(row.doc_id))
                    except Exception as exc:  # pragma: no cover - depends on broker state
                        row.status = IngestionTaskOutboxStatus.FAILED
                        row.dispatched_at = None
                        row.last_error = _format_error(exc)
                        row.next_retry_at = now + timedelta(
                            seconds=_compute_retry_delay_seconds(attempts=row.attempts)
                        )
                        logger.warning(
                            "Dispatch ingestion outbox row failed",
                            extra={
                                "outbox_id": str(row.id),
                                "batch_id": str(row.batch_id),
                                "doc_id": str(row.doc_id),
                                "attempts": row.attempts,
                                "error": row.last_error,
                            },
                        )
                    else:
                        row.status = IngestionTaskOutboxStatus.DISPATCHED
                        row.dispatched_at = now
                        row.last_error = None
                        row.next_retry_at = None
                        dispatched_rows += 1
                await session.commit()

        return dispatched_rows
