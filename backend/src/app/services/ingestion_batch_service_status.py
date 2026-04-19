from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.ingestion_batch import (
    IngestionBatch,
    IngestionBatchDoc,
    IngestionBatchStatus,
    IngestionDocStatus,
    IngestionEvent,
)
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseReadiness
from app.services.ingestion_batch_service_contracts import DOC_CANCELED_ERROR_CODE
from app.services.ingestion_contract import ingestion_error
from app.services.knowledge_base_service import touch_kb_updated_at


async def _get_batch_or_raise(
    self,
    *,
    batch_id: uuid.UUID,
    for_update: bool = False,
    populate_existing: bool = False,
) -> IngestionBatch:
    stmt = select(IngestionBatch).where(IngestionBatch.id == batch_id)
    stmt = stmt.options(selectinload(IngestionBatch.docs))
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    if for_update:
        stmt = stmt.with_for_update()
    batch = (await self._db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise ingestion_error(
            "BATCH_NOT_FOUND", details={"batch_id": str(batch_id)}
        )
    return batch


async def _set_doc_status(
    self,
    doc: IngestionBatchDoc,
    new_status: IngestionDocStatus,
    *,
    reason: str,
) -> None:
    old = doc.status
    if old == new_status:
        return

    allowed: dict[IngestionDocStatus, set[IngestionDocStatus]] = {
        IngestionDocStatus.QUEUED: {
            IngestionDocStatus.PROCESSING,
            IngestionDocStatus.CANCELED,
        },
        IngestionDocStatus.PROCESSING: {
            IngestionDocStatus.QUEUED,
            IngestionDocStatus.SUCCEEDED,
            IngestionDocStatus.FAILED,
            IngestionDocStatus.CANCELED,
        },
        IngestionDocStatus.FAILED: {IngestionDocStatus.QUEUED},
    }
    if new_status not in allowed.get(old, set()):
        raise ingestion_error(
            "BATCH_STATUS_CONFLICT",
            details={
                "entity": "doc",
                "doc_id": str(doc.id),
                "from_status": old.value,
                "to_status": new_status.value,
            },
        )

    doc.status = new_status
    await self._append_event(
        batch_id=doc.batch_id,
        doc_id=doc.id,
        from_status=old.value,
        to_status=new_status.value,
        reason=reason,
    )
    self._mark_batch_changed(doc.batch_id)


async def _set_batch_status(
    self,
    batch: IngestionBatch,
    new_status: IngestionBatchStatus,
    *,
    reason: str,
) -> None:
    old = batch.status
    if old == new_status:
        return

    allowed: dict[IngestionBatchStatus, set[IngestionBatchStatus]] = {
        IngestionBatchStatus.QUEUED: {
            IngestionBatchStatus.PROCESSING,
            IngestionBatchStatus.COMPLETED,
            IngestionBatchStatus.FAILED,
            IngestionBatchStatus.CANCELED,
        },
        IngestionBatchStatus.PROCESSING: {
            IngestionBatchStatus.QUEUED,
            IngestionBatchStatus.COMPLETED,
            IngestionBatchStatus.FAILED,
            IngestionBatchStatus.CANCELED,
        },
        IngestionBatchStatus.FAILED: {
            IngestionBatchStatus.QUEUED,
            IngestionBatchStatus.PROCESSING,
        },
        IngestionBatchStatus.CANCELED: {
            IngestionBatchStatus.QUEUED,
            IngestionBatchStatus.PROCESSING,
        },
    }
    if new_status not in allowed.get(old, set()):
        raise ingestion_error(
            "BATCH_STATUS_CONFLICT",
            details={
                "entity": "batch",
                "batch_id": str(batch.id),
                "from_status": old.value,
                "to_status": new_status.value,
            },
        )

    batch.status = new_status
    now = datetime.now(timezone.utc)
    terminal_statuses = {
        IngestionBatchStatus.COMPLETED,
        IngestionBatchStatus.FAILED,
        IngestionBatchStatus.CANCELED,
    }
    if new_status == IngestionBatchStatus.PROCESSING and batch.started_at is None:
        batch.started_at = now
    if new_status in terminal_statuses:
        batch.finished_at = now
    else:
        batch.finished_at = None

    await self._append_event(
        batch_id=batch.id,
        doc_id=None,
        from_status=old.value,
        to_status=new_status.value,
        reason=reason,
    )
    self._mark_batch_changed(batch.id)


async def _recalculate_batch(self, batch: IngestionBatch, *, reason: str) -> None:
    docs = list(batch.docs)
    total = len(docs)

    succeeded = sum(1 for doc in docs if self._is_doc_succeeded(doc))
    failed = sum(1 for doc in docs if self._is_doc_failed(doc))
    canceled = sum(1 for doc in docs if self._is_doc_canceled(doc))
    queued = sum(1 for doc in docs if doc.status == IngestionDocStatus.QUEUED)
    processing = sum(1 for doc in docs if doc.status == IngestionDocStatus.PROCESSING)

    batch.total_docs = total
    batch.succeeded_docs = succeeded
    batch.failed_docs = failed
    batch.canceled_docs = canceled
    batch.succeeded_chunks = sum(
        doc.chunk_count for doc in docs if self._is_doc_succeeded(doc)
    )

    if processing > 0:
        target_status = IngestionBatchStatus.PROCESSING
    elif queued > 0:
        target_status = IngestionBatchStatus.QUEUED
    elif failed > 0:
        target_status = IngestionBatchStatus.FAILED
    elif canceled > 0:
        target_status = IngestionBatchStatus.CANCELED
    else:
        target_status = IngestionBatchStatus.COMPLETED

    await self._set_batch_status(batch, target_status, reason=reason)
    if target_status in {
        IngestionBatchStatus.COMPLETED,
        IngestionBatchStatus.FAILED,
        IngestionBatchStatus.CANCELED,
    }:
        await self._apply_readiness(batch=batch)

    batch.error_summary = {
        "succeeded_docs": succeeded,
        "failed_docs": failed,
        "canceled_docs": canceled,
        "reason": reason,
    }
    self._mark_batch_changed(batch.id)


def _is_doc_canceled(doc: IngestionBatchDoc) -> bool:
    if doc.status == IngestionDocStatus.CANCELED:
        return True
    return (
        doc.status == IngestionDocStatus.FAILED
        and doc.error_code == DOC_CANCELED_ERROR_CODE
    )


def _is_doc_failed(doc: IngestionBatchDoc) -> bool:
    return doc.status == IngestionDocStatus.FAILED and not _is_doc_canceled(doc)


def _is_doc_succeeded(doc: IngestionBatchDoc) -> bool:
    return doc.status == IngestionDocStatus.SUCCEEDED


async def _apply_readiness(self, *, batch: IngestionBatch) -> None:
    kb = await self._db.get(KnowledgeBase, batch.kb_id)
    if kb is None:
        return

    if batch.is_bootstrap:
        if (
            batch.succeeded_docs >= 1
            and batch.succeeded_chunks >= 1
        ):
            kb.readiness = KnowledgeBaseReadiness.READY
        else:
            kb.readiness = KnowledgeBaseReadiness.NOT_READY
        kb.readiness_updated_at = datetime.now(timezone.utc)
    if (
        batch.status
        in {
            IngestionBatchStatus.COMPLETED,
            IngestionBatchStatus.FAILED,
            IngestionBatchStatus.CANCELED,
        }
        and batch.succeeded_chunks >= 1
    ):
        await touch_kb_updated_at(self._db, batch.kb_id)


async def _append_event(
    self,
    *,
    batch_id: uuid.UUID,
    doc_id: uuid.UUID | None,
    from_status: str | None,
    to_status: str,
    reason: str,
) -> None:
    self._db.add(
        IngestionEvent(
            batch_id=batch_id,
            doc_id=doc_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
        )
    )


@staticmethod
def _batch_snapshot_key(batch: IngestionBatch) -> tuple[Any, ...]:
    doc_states = tuple(
        sorted(
            (
                str(doc.id),
                doc.status.value,
                doc.retry_count,
                doc.retryable,
                doc.chunk_count,
                doc.error_code or "",
                doc.error_message or "",
            )
            for doc in batch.docs
        )
    )
    return (
        batch.status.value,
        batch.succeeded_docs,
        batch.failed_docs,
        batch.canceled_docs,
        batch.succeeded_chunks,
        batch.finished_at.isoformat() if batch.finished_at else "",
        doc_states,
    )
