"""从事务 outbox 分发导入文档任务的 Celery 任务。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.settings import get_settings
from app.models.ingestion_batch import IngestionBatchDoc, IngestionDocStatus
from app.models.ingestion_task_outbox import (
    IngestionTaskOutbox,
    IngestionTaskOutboxStatus,
)
from app.services.ingestion_batch_change_bus import open_ingestion_batch_change_bus
from app.services.ingestion_batch_service import IngestionBatchService
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources

logger = logging.getLogger(__name__)

DEFAULT_DISPATCH_BATCH_SIZE = 50
MAX_RETRY_BACKOFF_SECONDS = 600
RETRY_BASE_SECONDS = 5
MAX_ERROR_MESSAGE_LENGTH = 2000
DEFAULT_STALE_DISPATCHED_SECONDS = 60 * 60
STALE_RECOVERY_MESSAGE = "stale_dispatched_recovered"
DISPATCH_EXHAUSTED_ERROR_CODE = "DOC_DISPATCH_EXHAUSTED"
DISPATCH_EXHAUSTED_ERROR_MESSAGE = (
    "文档调度重试已耗尽，已自动结束，请检查 dispatch/ingestion worker 状态"
)
FINALIZABLE_EXHAUSTED_STATUSES = (
    IngestionTaskOutboxStatus.PENDING,
    IngestionTaskOutboxStatus.FAILED,
)


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
    stale_dispatched_seconds: int = DEFAULT_STALE_DISPATCHED_SECONDS,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    stale_before = current_time - timedelta(seconds=max(stale_dispatched_seconds, 1))
    stmt = (
        select(IngestionTaskOutbox)
        .join(IngestionBatchDoc, IngestionBatchDoc.id == IngestionTaskOutbox.doc_id)
        .where(
            IngestionTaskOutbox.status == IngestionTaskOutboxStatus.DISPATCHED,
            IngestionTaskOutbox.dispatched_at.is_not(None),
            IngestionTaskOutbox.dispatched_at <= stale_before,
            IngestionTaskOutbox.attempts < IngestionTaskOutbox.max_attempts,
            IngestionBatchDoc.status.in_(
                [IngestionDocStatus.QUEUED, IngestionDocStatus.PROCESSING]
            ),
        )
        .order_by(IngestionTaskOutbox.dispatched_at.asc(), IngestionTaskOutbox.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = IngestionTaskOutboxStatus.FAILED
        row.dispatched_at = None
        row.next_retry_at = current_time
        row.last_error = STALE_RECOVERY_MESSAGE
        logger.warning(
            "Recovered stale dispatched ingestion outbox row",
            extra={
                "outbox_id": str(row.id),
                "batch_id": str(row.batch_id),
                "doc_id": str(row.doc_id),
                "attempts": row.attempts,
            },
        )
    return len(rows)


async def _finalize_exhausted_outbox_rows(
    *,
    service: IngestionBatchService,
    limit: int,
) -> int:
    session = service._db
    stmt = (
        select(IngestionTaskOutbox)
        .join(IngestionBatchDoc, IngestionBatchDoc.id == IngestionTaskOutbox.doc_id)
        .where(
            IngestionTaskOutbox.attempts >= IngestionTaskOutbox.max_attempts,
            IngestionTaskOutbox.status.in_(FINALIZABLE_EXHAUSTED_STATUSES),
            IngestionBatchDoc.status.in_(
                [IngestionDocStatus.QUEUED, IngestionDocStatus.PROCESSING]
            ),
        )
        .order_by(IngestionTaskOutbox.updated_at.asc(), IngestionTaskOutbox.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return 0

    finalized = 0
    for row in rows:
        doc = await service.get_doc(doc_id=row.doc_id, for_update=True)
        if doc is None or doc.status not in {
            IngestionDocStatus.QUEUED,
            IngestionDocStatus.PROCESSING,
        }:
            continue
        await service.mark_doc_failed(
            doc=doc,
            outbox=row,
            error_code=DISPATCH_EXHAUSTED_ERROR_CODE,
            error_message=DISPATCH_EXHAUSTED_ERROR_MESSAGE,
            retryable=False,
        )
        await service.recalculate_batch_for_doc(
            doc=doc,
            reason="dispatch_attempts_exhausted",
        )
        finalized += 1
    return finalized


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


async def _dispatch_ingestion_outbox(
    *, limit: int = DEFAULT_DISPATCH_BATCH_SIZE
) -> int:
    settings = get_settings()
    safe_limit = max(int(limit or DEFAULT_DISPATCH_BATCH_SIZE), 1)
    stale_seconds = max(
        int(
            getattr(
                settings,
                "ingestion_outbox_stale_dispatched_seconds",
                DEFAULT_STALE_DISPATCHED_SECONDS,
            )
        ),
        1,
    )

    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_object_storage=True,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive guard
            return 0

        dispatched_rows = 0
        async with open_ingestion_batch_change_bus(settings=settings) as change_bus:
            async with sessionmaker() as session:
                if resources.object_storage is None:  # pragma: no cover - defensive guard
                    return 0
                service = IngestionBatchService(
                    session,
                    object_storage=resources.object_storage,
                    change_bus=change_bus,
                )
                while True:
                    await _recover_stale_dispatched_rows(
                        session=session,
                        limit=safe_limit,
                        stale_dispatched_seconds=stale_seconds,
                    )
                    finalized_rows = await _finalize_exhausted_outbox_rows(
                        service=service,
                        limit=safe_limit,
                    )
                    rows = await _claim_due_outbox_rows(session=session, limit=safe_limit)
                    if not rows:
                        if finalized_rows > 0:
                            await service.commit()
                        else:
                            await service.rollback()
                        break

                    from app.worker.tasks.ingestion_batches import run_ingestion_batch_doc

                    for row in rows:
                        now = datetime.now(timezone.utc)
                        row.attempts += 1
                        try:
                            run_ingestion_batch_doc.delay(str(row.doc_id))
                        except (
                            Exception
                        ) as exc:  # pragma: no cover - depends on broker state
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
                    await service.commit()

        return dispatched_rows
