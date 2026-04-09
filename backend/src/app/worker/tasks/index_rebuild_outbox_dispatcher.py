"""从事务 outbox 分发索引重建作业的 Celery 任务。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.settings import get_settings
from app.models.index_rebuild_job import IndexRebuildJob, IndexRebuildStatus
from app.models.index_rebuild_task_outbox import (
    IndexRebuildTaskOutbox,
    IndexRebuildTaskOutboxStatus,
)
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources

logger = logging.getLogger(__name__)

DEFAULT_DISPATCH_BATCH_SIZE = 50
MAX_RETRY_BACKOFF_SECONDS = 600
RETRY_BASE_SECONDS = 5
MAX_ERROR_MESSAGE_LENGTH = 2000
STALE_DISPATCHED_SECONDS = 60 * 60
STALE_RECOVERY_MESSAGE = "stale_dispatched_recovered"


def _compute_retry_delay_seconds(*, attempts: int) -> int:
    bounded_attempt = max(1, min(attempts, 10))
    return min(
        MAX_RETRY_BACKOFF_SECONDS, RETRY_BASE_SECONDS * (2 ** (bounded_attempt - 1))
    )


def _format_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:MAX_ERROR_MESSAGE_LENGTH]


async def _recover_stale_dispatched_rows(
    *,
    session,  # noqa: ANN001
    limit: int,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    stale_before = current_time - timedelta(seconds=STALE_DISPATCHED_SECONDS)
    stmt = (
        select(IndexRebuildTaskOutbox)
        .join(IndexRebuildJob, IndexRebuildJob.id == IndexRebuildTaskOutbox.job_id)
        .where(
            IndexRebuildTaskOutbox.status == IndexRebuildTaskOutboxStatus.DISPATCHED,
            IndexRebuildTaskOutbox.dispatched_at.is_not(None),
            IndexRebuildTaskOutbox.dispatched_at <= stale_before,
            IndexRebuildTaskOutbox.attempts < IndexRebuildTaskOutbox.max_attempts,
            IndexRebuildJob.status.in_(
                [IndexRebuildStatus.QUEUED, IndexRebuildStatus.RUNNING]
            ),
        )
        .order_by(
            IndexRebuildTaskOutbox.dispatched_at.asc(), IndexRebuildTaskOutbox.id.asc()
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = IndexRebuildTaskOutboxStatus.FAILED
        row.dispatched_at = None
        row.next_retry_at = current_time
        row.last_error = STALE_RECOVERY_MESSAGE
        logger.warning(
            "Recovered stale dispatched index rebuild outbox row",
            extra={
                "outbox_id": str(row.id),
                "job_id": str(row.job_id),
                "attempts": row.attempts,
            },
        )
    return len(rows)


async def _claim_due_outbox_rows(
    *, session, limit: int
) -> list[IndexRebuildTaskOutbox]:  # noqa: ANN001
    now = datetime.now(timezone.utc)
    stmt = (
        select(IndexRebuildTaskOutbox)
        .join(IndexRebuildJob, IndexRebuildJob.id == IndexRebuildTaskOutbox.job_id)
        .where(
            IndexRebuildTaskOutbox.status.in_(
                [
                    IndexRebuildTaskOutboxStatus.PENDING,
                    IndexRebuildTaskOutboxStatus.FAILED,
                ]
            ),
            or_(
                IndexRebuildTaskOutbox.next_retry_at.is_(None),
                IndexRebuildTaskOutbox.next_retry_at <= now,
            ),
            IndexRebuildTaskOutbox.attempts < IndexRebuildTaskOutbox.max_attempts,
            IndexRebuildJob.status.in_(
                [IndexRebuildStatus.QUEUED, IndexRebuildStatus.RUNNING]
            ),
        )
        .order_by(
            IndexRebuildTaskOutbox.created_at.asc(), IndexRebuildTaskOutbox.id.asc()
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = IndexRebuildTaskOutboxStatus.DISPATCHING
    return rows


@celery_app.task(
    name="app.worker.tasks.index_rebuild_outbox_dispatcher.dispatch_index_rebuild_outbox"
)
def dispatch_index_rebuild_outbox(limit: int = DEFAULT_DISPATCH_BATCH_SIZE) -> None:
    asyncio.run(_dispatch_index_rebuild_outbox(limit=limit))


async def _dispatch_index_rebuild_outbox(
    *, limit: int = DEFAULT_DISPATCH_BATCH_SIZE
) -> int:
    settings = get_settings()
    safe_limit = max(int(limit or DEFAULT_DISPATCH_BATCH_SIZE), 1)

    async with managed_task_resources(settings=settings, with_engine=True) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive guard
            return 0

        dispatched_rows = 0
        async with sessionmaker() as session:
            while True:
                await _recover_stale_dispatched_rows(
                    session=session,
                    limit=safe_limit,
                )
                rows = await _claim_due_outbox_rows(session=session, limit=safe_limit)
                if not rows:
                    await session.rollback()
                    break

                from app.worker.tasks.index_rebuild import run_index_rebuild_job

                for row in rows:
                    now = datetime.now(timezone.utc)
                    row.attempts += 1
                    try:
                        run_index_rebuild_job.delay(str(row.job_id))
                    except (
                        Exception
                    ) as exc:  # pragma: no cover - depends on broker state
                        row.status = IndexRebuildTaskOutboxStatus.FAILED
                        row.dispatched_at = None
                        row.last_error = _format_error(exc)
                        row.next_retry_at = now + timedelta(
                            seconds=_compute_retry_delay_seconds(attempts=row.attempts)
                        )
                        logger.warning(
                            "Dispatch index rebuild outbox row failed",
                            extra={
                                "outbox_id": str(row.id),
                                "job_id": str(row.job_id),
                                "attempts": row.attempts,
                                "error": row.last_error,
                            },
                        )
                    else:
                        row.status = IndexRebuildTaskOutboxStatus.DISPATCHED
                        row.dispatched_at = now
                        row.last_error = None
                        row.next_retry_at = None
                        dispatched_rows += 1
                await session.commit()

        return dispatched_rows
