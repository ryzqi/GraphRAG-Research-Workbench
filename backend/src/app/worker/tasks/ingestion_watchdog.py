"""Watchdog tasks for stale ingestion docs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.settings import get_settings
from app.models.ingestion_batch import IngestionBatchDoc, IngestionDocStatus
from app.models.ingestion_task_outbox import (
    IngestionTaskOutbox,
    IngestionTaskOutboxStatus,
)
from app.services.ingestion_batch_service import INGESTION_DOC_TASK_NAME, IngestionBatchService
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources

DEFAULT_DOC_WATCHDOG_BATCH_SIZE = 100
DOC_QUEUE_TIMEOUT_ERROR_CODE = "DOC_QUEUE_TIMEOUT"
DOC_DISPATCH_EXHAUSTED_ERROR_CODE = "DOC_DISPATCH_EXHAUSTED"
DOC_QUEUE_TIMEOUT_MESSAGE = "文档处理超时，已自动结束，请检查 ingestion worker 状态"
DOC_DISPATCH_EXHAUSTED_MESSAGE = "文档调度重试已耗尽，已自动结束，请检查 dispatch/ingestion worker 状态"


def _resolve_doc_timeout_error_code(*, attempts: int, max_attempts: int) -> str:
    if max_attempts > 0 and attempts >= max_attempts:
        return DOC_DISPATCH_EXHAUSTED_ERROR_CODE
    return DOC_QUEUE_TIMEOUT_ERROR_CODE


def _resolve_doc_timeout_error_message(*, error_code: str) -> str:
    if error_code == DOC_DISPATCH_EXHAUSTED_ERROR_CODE:
        return DOC_DISPATCH_EXHAUSTED_MESSAGE
    return DOC_QUEUE_TIMEOUT_MESSAGE


@celery_app.task(name="app.worker.tasks.ingestion_watchdog.fail_stale_processing_docs")
def fail_stale_processing_docs(limit: int = DEFAULT_DOC_WATCHDOG_BATCH_SIZE) -> None:
    asyncio.run(_fail_stale_processing_docs(limit=limit))


async def _fail_stale_processing_docs(
    *,
    limit: int = DEFAULT_DOC_WATCHDOG_BATCH_SIZE,
) -> int:
    settings = get_settings()
    safe_limit = max(int(limit or DEFAULT_DOC_WATCHDOG_BATCH_SIZE), 1)
    timeout_seconds = max(int(settings.ingestion_doc_queue_timeout_seconds), 1)

    async with managed_task_resources(settings=settings, with_engine=True) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive guard
            return 0

        processed = 0
        async with sessionmaker() as session:
            now = datetime.now(timezone.utc)
            stale_before = now - timedelta(seconds=timeout_seconds)
            stmt = (
                select(IngestionBatchDoc.id)
                .where(
                    IngestionBatchDoc.status == IngestionDocStatus.PROCESSING,
                    IngestionBatchDoc.updated_at <= stale_before,
                )
                .order_by(IngestionBatchDoc.updated_at.asc(), IngestionBatchDoc.id.asc())
                .limit(safe_limit)
                .with_for_update(skip_locked=True)
            )
            doc_ids = [row[0] for row in (await session.execute(stmt)).all()]
            if not doc_ids:
                await session.rollback()
                return 0

            service = IngestionBatchService(session)
            for doc_id in doc_ids:
                doc = await service.get_doc(doc_id=doc_id, for_update=True)
                if doc is None or doc.status != IngestionDocStatus.PROCESSING:
                    continue

                outbox_stmt = (
                    select(IngestionTaskOutbox)
                    .where(
                        IngestionTaskOutbox.doc_id == doc.id,
                        IngestionTaskOutbox.task_name == INGESTION_DOC_TASK_NAME,
                    )
                    .order_by(IngestionTaskOutbox.created_at.desc(), IngestionTaskOutbox.id.desc())
                    .limit(1)
                    .with_for_update()
                )
                outbox = (await session.execute(outbox_stmt)).scalar_one_or_none()
                attempts = int(getattr(outbox, "attempts", 0) or 0)
                max_attempts = int(getattr(outbox, "max_attempts", 0) or 0)
                error_code = _resolve_doc_timeout_error_code(
                    attempts=attempts,
                    max_attempts=max_attempts,
                )
                error_message = _resolve_doc_timeout_error_message(error_code=error_code)

                await service.mark_doc_failed(
                    doc=doc,
                    error_code=error_code,
                    error_message=error_message,
                    retryable=False,
                )
                await service.recalculate_batch_for_doc(
                    doc=doc,
                    reason="doc_timeout_watchdog",
                )

                if outbox is not None:
                    outbox.status = IngestionTaskOutboxStatus.FAILED
                    outbox.last_error = error_code
                    outbox.next_retry_at = None
                    outbox.dispatched_at = None
                processed += 1
            await session.commit()

        return processed

