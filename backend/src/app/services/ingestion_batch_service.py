"""统一 ingestion-batch 编排服务。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.settings import get_settings
from app.integrations.object_storage import ObjectStorage
from app.models.ingestion_batch import (
    IngestionBatch,
    IngestionBatchDoc,
    IngestionBatchStatus,
    IngestionDocStatus,
)
from app.models.ingestion_task_outbox import (
    IngestionTaskOutbox,
    IngestionTaskOutboxStatus,
)
from app.models.knowledge_base import KnowledgeBase
from app.schemas.ingestion_batches import (
    BatchStatus,
    EntryErrorRead,
    IngestionBatchCancelResponse,
    IngestionBatchRead,
    IngestionBatchRetryResponse,
    IngestionBatchSubmitResponse,
    KnowledgeBaseIngestionStateRead,
    ManifestEntry,
)
from app.services.ingestion_batch_change_bus import (
    INGESTION_BATCH_CHANGED_EVENT,
    IngestionBatchChangeBus,
)
from app.services import ingestion_batch_service_prepare as ingestion_prepare
from app.services import ingestion_batch_service_status as ingestion_status
from app.services.ingestion_batch_service_contracts import (
    AUTO_RETRY_DELAYS,
    DOC_CANCELED_ERROR_CODE,
    INGESTION_DOC_TASK_NAME,
    MAX_DOC_ATTEMPTS,
    MAX_MANIFEST_ENTRIES,
)
from app.services.ingestion_contract import ingestion_error
from app.services.streaming import stream_snapshots
from app.services.url_ingestion_guard import build_url_ingestion_guard

logger = logging.getLogger(__name__)

__all__ = ['INGESTION_DOC_TASK_NAME', 'IngestionBatchService']

_STATIC_HELPERS: dict[str, Any] = {
    '_is_doc_canceled': ingestion_status._is_doc_canceled,
    '_is_doc_failed': ingestion_status._is_doc_failed,
    '_is_doc_succeeded': ingestion_status._is_doc_succeeded,
    '_batch_snapshot_key': ingestion_status._batch_snapshot_key,
    '_entry_error_from_app_error': ingestion_prepare._entry_error_from_app_error,
    '_material_extension': ingestion_prepare._material_extension,
    '_is_bootstrap_conflict': ingestion_prepare._is_bootstrap_conflict,
}

_INSTANCE_HELPERS: dict[str, Any] = {
    '_create_batch_with_retry': ingestion_prepare._create_batch_with_retry,
    '_prepare_entries': ingestion_prepare._prepare_entries,
    '_prepare_text_entry': ingestion_prepare._prepare_text_entry,
    '_prepare_url_entry': ingestion_prepare._prepare_url_entry,
    '_prepare_file_entry': ingestion_prepare._prepare_file_entry,
    '_materialize_source_material': ingestion_prepare._materialize_source_material,
    '_ensure_current_snapshot': ingestion_prepare._ensure_current_snapshot,
    '_ensure_outbox_for_docs': ingestion_prepare._ensure_outbox_for_docs,
    '_trigger_outbox_dispatch': ingestion_prepare._trigger_outbox_dispatch,
    '_material_file_size': ingestion_prepare._material_file_size,
    '_get_batch_or_raise': ingestion_status._get_batch_or_raise,
    '_set_doc_status': ingestion_status._set_doc_status,
    '_set_batch_status': ingestion_status._set_batch_status,
    '_recalculate_batch': ingestion_status._recalculate_batch,
    '_apply_readiness': ingestion_status._apply_readiness,
    '_append_event': ingestion_status._append_event,
}


class IngestionBatchService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        http_client: httpx.AsyncClient | None = None,
        object_storage: ObjectStorage,
        change_bus: IngestionBatchChangeBus | None = None,
    ) -> None:
        self._db = db
        self._settings = get_settings()
        self._storage = object_storage
        self._change_bus = change_bus
        self._pending_batch_changes: set[uuid.UUID] = set()
        self._url_guard = build_url_ingestion_guard(
            self._settings,
            http_client=http_client,
        )

    def __getattr__(self, name: str) -> Any:
        helper = _STATIC_HELPERS.get(name)
        if helper is not None:
            return helper
        helper = _INSTANCE_HELPERS.get(name)
        if helper is not None:
            return partial(helper, self)
        raise AttributeError(f'{type(self).__name__!s} has no attribute {name!r}')

    async def submit_manifest(
        self,
        *,
        kb_id: uuid.UUID,
        entries: list[ManifestEntry],
        requested_by: str | None = None,
    ) -> IngestionBatchSubmitResponse:
        if len(entries) > MAX_MANIFEST_ENTRIES:
            raise ingestion_error(
                'MANIFEST_LIMIT_EXCEEDED',
                details={'max_entries': MAX_MANIFEST_ENTRIES, 'total_entries': len(entries)},
            )
        kb = await self._db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ingestion_error('KB_NOT_FOUND')
        entry_errors: list[EntryErrorRead] = []
        prepared_entries = await self._prepare_entries(
            kb=kb,
            entries=entries,
            entry_errors=entry_errors,
        )
        if not prepared_entries:
            raise ingestion_error(
                'MANIFEST_ALL_ENTRIES_FAILED',
                details={'entry_errors': [err.model_dump(mode='json') for err in entry_errors]},
            )

        batch: IngestionBatch | None = None
        docs: list[IngestionBatchDoc] = []
        for attempt in range(2):
            try:
                batch, docs = await self._create_batch_with_retry(
                    kb_id=kb.id,
                    prepared_entries=prepared_entries,
                    requested_by=requested_by,
                )
                break
            except Exception as exc:
                await self._db.rollback()
                if attempt == 0 and self._is_bootstrap_conflict(exc):
                    continue
                raise ingestion_error('KB_BOOTSTRAP_CONFLICT') from exc
        if batch is None:
            raise ingestion_error('KB_BOOTSTRAP_CONFLICT')

        try:
            self._trigger_outbox_dispatch()
        except Exception as exc:  # pragma: no cover
            logger.warning(
                'Failed to trigger ingestion outbox dispatcher after submit',
                extra={'error': str(exc)},
            )

        return IngestionBatchSubmitResponse(
            batch_id=batch.id,
            kb_id=batch.kb_id,
            status=BatchStatus(batch.status.value),
            is_bootstrap=batch.is_bootstrap,
            config_snapshot_id=batch.config_snapshot_id,
            config_version=batch.config_version,
            total_docs=batch.total_docs,
            accepted_docs=len(docs),
            failed_docs=len(entry_errors),
            entry_errors=entry_errors,
        )

    async def get_batch(self, *, batch_id: uuid.UUID) -> IngestionBatchRead:
        batch = await self._get_batch_or_raise(batch_id=batch_id)
        return IngestionBatchRead.model_validate(batch)

    async def get_latest_batch_for_kb(
        self,
        *,
        kb_id: uuid.UUID,
        prefer_active: bool = True,
    ) -> IngestionBatchRead | None:
        kb = await self._db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ingestion_error('KB_NOT_FOUND')
        batch: IngestionBatch | None = None
        if prefer_active:
            batch = await self.get_active_batch_for_kb(kb_id=kb_id, with_docs=True)
        if batch is None:
            stmt = (
                select(IngestionBatch)
                .where(IngestionBatch.kb_id == kb_id)
                .options(selectinload(IngestionBatch.docs))
                .order_by(IngestionBatch.created_at.desc(), IngestionBatch.id.desc())
                .limit(1)
            )
            batch = (await self._db.execute(stmt)).scalar_one_or_none()
        if batch is None:
            return None
        return IngestionBatchRead.model_validate(batch)

    async def stream_batch_updates(
        self,
        *,
        batch_id: uuid.UUID,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 10.0,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        terminal_statuses = {
            IngestionBatchStatus.COMPLETED,
            IngestionBatchStatus.FAILED,
            IngestionBatchStatus.CANCELED,
        }

        async def _fetch_batch() -> IngestionBatch:
            return await self._get_batch_or_raise(
                batch_id=batch_id,
                populate_existing=True,
            )

        def _serialize_batch(batch: IngestionBatch) -> dict[str, Any]:
            return IngestionBatchRead.model_validate(batch).model_dump(mode='json')

        def _heartbeat_payload() -> dict[str, Any]:
            return {
                'batch_id': str(batch_id),
                'ts': datetime.now(timezone.utc).isoformat(),
            }

        stream_kwargs = {
            'fetcher': _fetch_batch,
            'serializer': _serialize_batch,
            'is_terminal': lambda batch: batch.status in terminal_statuses,
            'poll_interval': poll_interval,
            'heartbeat_interval': heartbeat_interval,
            'heartbeat_factory': _heartbeat_payload,
            'initial_event': 'snapshot',
        }

        try:
            if self._change_bus is None:
                async for event, payload in stream_snapshots(**stream_kwargs):
                    yield event, payload
                return

            try:
                async with self._change_bus.listen(batch_id=batch_id) as listener:
                    async for event, payload in stream_snapshots(
                        change_listener=listener,
                        **stream_kwargs,
                    ):
                        yield event, payload
            except Exception as exc:
                logger.warning(
                    'Failed to subscribe ingestion batch change listener; falling back to polling',
                    extra={'batch_id': str(batch_id), 'error': str(exc)},
                )
                async for event, payload in stream_snapshots(**stream_kwargs):
                    yield event, payload
        except asyncio.CancelledError:
            return

    async def get_kb_ingestion_state(
        self,
        *,
        kb_id: uuid.UUID,
    ) -> KnowledgeBaseIngestionStateRead:
        kb = await self._db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ingestion_error('KB_NOT_FOUND')

        active_batch = await self.get_active_batch_for_kb(kb_id=kb_id)
        if active_batch is None:
            return KnowledgeBaseIngestionStateRead(
                kb_id=kb_id,
                has_active_batch=False,
                active_batch_id=None,
                active_batch_status=None,
                updated_at=datetime.now(timezone.utc),
            )

        return KnowledgeBaseIngestionStateRead(
            kb_id=kb_id,
            has_active_batch=True,
            active_batch_id=active_batch.id,
            active_batch_status=BatchStatus(active_batch.status.value),
            updated_at=datetime.now(timezone.utc),
        )

    async def get_active_batch_for_kb(
        self,
        *,
        kb_id: uuid.UUID,
        with_docs: bool = False,
    ) -> IngestionBatch | None:
        stmt = (
            select(IngestionBatch)
            .where(
                IngestionBatch.kb_id == kb_id,
                IngestionBatch.status.in_(
                    [
                        IngestionBatchStatus.QUEUED,
                        IngestionBatchStatus.PROCESSING,
                    ]
                ),
            )
            .order_by(IngestionBatch.created_at.desc(), IngestionBatch.id.desc())
            .limit(1)
        )
        if with_docs:
            stmt = stmt.options(selectinload(IngestionBatch.docs))

        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def retry_failed_docs(
        self,
        *,
        batch_id: uuid.UUID,
    ) -> IngestionBatchRetryResponse:
        batch = await self._get_batch_or_raise(batch_id=batch_id, for_update=True)
        requeued_doc_ids: list[uuid.UUID] = []
        ignored_docs = 0

        for doc in list(batch.docs):
            if not self._is_doc_failed(doc):
                ignored_docs += 1
                continue
            if doc.retry_count >= MAX_DOC_ATTEMPTS:
                ignored_docs += 1
                continue

            await self._set_doc_status(
                doc,
                IngestionDocStatus.QUEUED,
                reason='manual_retry',
            )
            doc.retryable = True
            doc.error_code = None
            doc.error_message = None
            requeued_doc_ids.append(doc.id)

        if not requeued_doc_ids:
            raise ingestion_error('DOC_RETRY_NOT_ALLOWED')

        await self._ensure_outbox_for_docs(
            doc_ids=requeued_doc_ids,
            batch_id=batch.id,
        )
        await self._recalculate_batch(batch, reason='manual_retry')
        await self.commit()
        try:
            self._trigger_outbox_dispatch()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                'Failed to trigger ingestion outbox dispatcher after retry',
                extra={'error': str(exc)},
            )

        return IngestionBatchRetryResponse(
            batch_id=batch.id,
            status=BatchStatus(batch.status.value),
            requeued_docs=len(requeued_doc_ids),
            ignored_docs=ignored_docs,
        )

    async def cancel_batch(self, *, batch_id: uuid.UUID) -> IngestionBatchCancelResponse:
        batch = await self._get_batch_or_raise(batch_id=batch_id, for_update=True)
        if batch.status not in {
            IngestionBatchStatus.QUEUED,
            IngestionBatchStatus.PROCESSING,
        }:
            raise ingestion_error(
                'BATCH_STATUS_CONFLICT',
                details={'status': batch.status.value},
            )

        canceled_docs = 0
        for doc in list(batch.docs):
            if doc.status not in {
                IngestionDocStatus.QUEUED,
                IngestionDocStatus.PROCESSING,
            }:
                continue
            doc.retryable = False
            doc.error_code = DOC_CANCELED_ERROR_CODE
            doc.error_message = '批次已取消'
            await self._set_doc_status(
                doc,
                IngestionDocStatus.CANCELED,
                reason='batch_cancel',
            )
            canceled_docs += 1

        await self._recalculate_batch(batch, reason='batch_cancel')
        await self.commit()

        return IngestionBatchCancelResponse(
            batch_id=batch.id,
            status=BatchStatus(batch.status.value),
            canceled_docs=canceled_docs,
            finished_at=batch.finished_at,
        )

    async def get_doc(
        self,
        *,
        doc_id: uuid.UUID,
        for_update: bool = False,
    ) -> IngestionBatchDoc | None:
        stmt = select(IngestionBatchDoc).where(IngestionBatchDoc.id == doc_id)
        stmt = stmt.options(selectinload(IngestionBatchDoc.batch))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_doc_outbox(
        self,
        *,
        doc_id: uuid.UUID,
        for_update: bool = False,
    ) -> IngestionTaskOutbox | None:
        stmt = (
            select(IngestionTaskOutbox)
            .where(
                IngestionTaskOutbox.doc_id == doc_id,
                IngestionTaskOutbox.task_name == INGESTION_DOC_TASK_NAME,
            )
            .order_by(
                IngestionTaskOutbox.created_at.desc(),
                IngestionTaskOutbox.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_doc_running(self, *, doc: IngestionBatchDoc) -> None:
        if doc.retry_count >= MAX_DOC_ATTEMPTS:
            raise ingestion_error(
                'DOC_RETRY_LIMIT_REACHED',
                details={'doc_id': str(doc.id), 'retry_count': doc.retry_count},
            )

        if doc.status in {
            IngestionDocStatus.QUEUED,
            IngestionDocStatus.PROCESSING,
        }:
            pass
        else:
            raise ingestion_error(
                'DOC_RETRY_NOT_ALLOWED',
                details={'doc_id': str(doc.id), 'status': doc.status.value},
            )

        doc.retry_count += 1
        await self._set_doc_status(doc, IngestionDocStatus.PROCESSING, reason='doc_start')
        doc.retryable = doc.retry_count < MAX_DOC_ATTEMPTS

    async def mark_doc_succeeded(
        self,
        *,
        doc: IngestionBatchDoc,
        outbox: IngestionTaskOutbox | None = None,
        chunk_count: int,
        context_failed_chunks: list[dict] | None = None,
    ) -> None:
        doc.chunk_count = max(chunk_count, 0)
        doc.context_failed_chunks = context_failed_chunks or None
        doc.retryable = False
        doc.error_code = None
        doc.error_message = None
        await self._set_doc_status(
            doc,
            IngestionDocStatus.SUCCEEDED,
            reason='doc_succeeded',
        )
        if outbox is not None:
            outbox.status = IngestionTaskOutboxStatus.SUCCEEDED
            outbox.next_retry_at = None
            outbox.dispatched_at = None
            outbox.last_error = None

    async def mark_doc_failed(
        self,
        *,
        doc: IngestionBatchDoc,
        outbox: IngestionTaskOutbox | None = None,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime | None = None,
    ) -> int | None:
        auto_retry_delay: int | None = None
        auto_retryable = retryable and doc.retry_count <= len(AUTO_RETRY_DELAYS)
        within_attempt_limit = doc.retry_count < MAX_DOC_ATTEMPTS
        current_time = now or datetime.now(timezone.utc)

        doc.context_failed_chunks = None
        if auto_retryable and within_attempt_limit:
            delay = AUTO_RETRY_DELAYS[doc.retry_count - 1]
            doc.retryable = True
            doc.error_code = error_code
            doc.error_message = error_message
            await self._set_doc_status(
                doc,
                IngestionDocStatus.QUEUED,
                reason='auto_retry',
            )
            if outbox is not None:
                outbox.status = IngestionTaskOutboxStatus.FAILED
                outbox.next_retry_at = current_time + timedelta(seconds=delay)
                outbox.dispatched_at = None
                outbox.last_error = error_code
            else:
                auto_retry_delay = delay
        else:
            doc.retryable = retryable and within_attempt_limit
            doc.error_code = error_code
            doc.error_message = error_message
            await self._set_doc_status(
                doc,
                IngestionDocStatus.FAILED,
                reason='doc_failed',
            )
            if outbox is not None:
                outbox.status = IngestionTaskOutboxStatus.FAILED
                outbox.next_retry_at = None
                outbox.dispatched_at = None
                outbox.last_error = error_code

        return auto_retry_delay

    async def recalculate_batch_for_doc(self, *, doc: IngestionBatchDoc, reason: str) -> None:
        batch = await self._get_batch_or_raise(
            batch_id=doc.batch_id,
            for_update=True,
            populate_existing=True,
        )
        await self._recalculate_batch(batch, reason=reason)

    async def commit(self) -> None:
        changed_batch_ids = tuple(self._pending_batch_changes)
        await self._db.commit()
        self._pending_batch_changes.clear()
        if self._change_bus is None:
            return
        for changed_batch_id in changed_batch_ids:
            await self._change_bus.publish(
                batch_id=changed_batch_id,
                event=INGESTION_BATCH_CHANGED_EVENT,
            )

    async def rollback(self) -> None:
        await self._db.rollback()
        self._pending_batch_changes.clear()

    def _mark_batch_changed(self, batch_id: uuid.UUID) -> None:
        self._pending_batch_changes.add(batch_id)
