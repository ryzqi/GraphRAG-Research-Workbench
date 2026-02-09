"""Unified ingestion-batch orchestration service."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import math
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, AsyncIterator
from urllib.parse import urljoin, urlparse, urlunparse

import anyio
import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.settings import get_settings
from app.integrations.object_storage import ObjectRef, ObjectStorage
from app.models.ingestion_batch import (
    IngestionBatch,
    IngestionBatchDoc,
    IngestionBatchStatus,
    IngestionDocStatus,
    IngestionEvent,
    IngestionSourceType,
)
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseReadiness
from app.models.source_material import SourceMaterial, SourceType
from app.schemas.ingestion_batches import (
    BatchStatus,
    EntryErrorRead,
    IngestionBatchCancelResponse,
    IngestionBatchRead,
    IngestionBatchRetryResponse,
    IngestionBatchSubmitResponse,
    KnowledgeBaseIngestionStateRead,
    ManifestEntry,
    ManifestFileEntry,
    ManifestSourceType,
    ManifestTextEntry,
    ManifestUrlEntry,
)
from app.services.ingestion_contract import INGESTION_ERROR_SPECS, ingestion_error

MAX_MANIFEST_ENTRIES = 100
MAX_TEXT_LENGTH = 200_000
MAX_URL_ENTRIES = 50
MAX_FILE_ENTRIES = 50
MAX_URL_REDIRECTS = 3
MAX_URL_TIMEOUT_SECONDS = 25
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
ALLOWED_FILE_EXTENSIONS = {".pdf", ".md", ".txt", ".docx"}
AUTO_RETRY_DELAYS = (30, 120)
MAX_DOC_ATTEMPTS = 5

_URL_BLOCKED_IPV4 = {ipaddress.ip_address("169.254.169.254")}


@dataclass(slots=True)
class _PreparedEntry:
    entry_id: str
    source_type: ManifestSourceType
    title: str | None
    payload: dict[str, Any]
    fingerprint: str


class IngestionBatchService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._settings = get_settings()

    async def submit_manifest(
        self,
        *,
        kb_id: uuid.UUID,
        entries: list[ManifestEntry],
        requested_by: str | None = None,
    ) -> IngestionBatchSubmitResponse:
        if len(entries) > MAX_MANIFEST_ENTRIES:
            raise ingestion_error(
                "MANIFEST_LIMIT_EXCEEDED",
                details={"max_entries": MAX_MANIFEST_ENTRIES, "total_entries": len(entries)},
            )

        kb = await self._db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ingestion_error("KB_NOT_FOUND")

        entry_errors: list[EntryErrorRead] = []
        prepared_entries = await self._prepare_entries(
            kb=kb,
            entries=entries,
            entry_errors=entry_errors,
        )

        if not prepared_entries:
            raise ingestion_error(
                "MANIFEST_ALL_ENTRIES_FAILED",
                details={"entry_errors": [err.model_dump(mode="json") for err in entry_errors]},
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
            except IntegrityError as exc:
                await self._db.rollback()
                if attempt == 0 and self._is_bootstrap_conflict(exc):
                    continue
                raise ingestion_error("KB_BOOTSTRAP_CONFLICT") from exc

        if batch is None:
            raise ingestion_error("KB_BOOTSTRAP_CONFLICT")

        self._enqueue_docs([doc.id for doc in docs])

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
            raise ingestion_error("KB_NOT_FOUND")

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
            IngestionBatchStatus.SUCCEEDED,
            IngestionBatchStatus.PARTIAL_FAILED,
            IngestionBatchStatus.FAILED,
            IngestionBatchStatus.CANCELED,
        }

        batch = await self._get_batch_or_raise(
            batch_id=batch_id,
            populate_existing=True,
        )
        snapshot_payload = IngestionBatchRead.model_validate(batch).model_dump(mode="json")
        yield "snapshot", snapshot_payload

        if batch.status in terminal_statuses:
            yield "final", snapshot_payload
            return

        last_snapshot_key = self._batch_snapshot_key(batch)
        last_event_count = await self._get_event_count(batch_id=batch_id)
        last_emit_at = monotonic()

        try:
            while True:
                await asyncio.sleep(poll_interval)

                batch = await self._get_batch_or_raise(
                    batch_id=batch_id,
                    populate_existing=True,
                )
                payload = IngestionBatchRead.model_validate(batch).model_dump(mode="json")
                snapshot_key = self._batch_snapshot_key(batch)
                event_count = await self._get_event_count(batch_id=batch_id)
                changed = snapshot_key != last_snapshot_key or event_count != last_event_count

                if changed:
                    if batch.status in terminal_statuses:
                        yield "final", payload
                        return
                    yield "update", payload
                    last_snapshot_key = snapshot_key
                    last_event_count = event_count
                    last_emit_at = monotonic()
                    continue

                if monotonic() - last_emit_at >= heartbeat_interval:
                    yield "heartbeat", {
                        "batch_id": str(batch_id),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                    last_emit_at = monotonic()
        except asyncio.CancelledError:
            return

    async def get_kb_ingestion_state(
        self,
        *,
        kb_id: uuid.UUID,
    ) -> KnowledgeBaseIngestionStateRead:
        kb = await self._db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ingestion_error("KB_NOT_FOUND")

        active_batch = await self.get_active_batch_for_kb(kb_id=kb_id, with_docs=True)
        if active_batch is None:
            return KnowledgeBaseIngestionStateRead(
                kb_id=kb_id,
                has_active_batch=False,
                active_batch_id=None,
                active_batch_status=None,
                pending_docs=0,
                running_docs=0,
                updated_at=datetime.now(timezone.utc),
            )

        pending_docs = sum(
            1 for doc in active_batch.docs if doc.status == IngestionDocStatus.PENDING
        )
        running_docs = sum(
            1 for doc in active_batch.docs if doc.status == IngestionDocStatus.RUNNING
        )

        return KnowledgeBaseIngestionStateRead(
            kb_id=kb_id,
            has_active_batch=True,
            active_batch_id=active_batch.id,
            active_batch_status=BatchStatus(active_batch.status.value),
            pending_docs=pending_docs,
            running_docs=running_docs,
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
                    (IngestionBatchStatus.QUEUED, IngestionBatchStatus.RUNNING)
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
            if doc.status != IngestionDocStatus.FAILED:
                ignored_docs += 1
                continue
            if doc.retry_count >= MAX_DOC_ATTEMPTS:
                ignored_docs += 1
                continue

            await self._set_doc_status(doc, IngestionDocStatus.PENDING, reason="manual_retry")
            doc.retryable = True
            doc.error_code = None
            doc.error_message = None
            requeued_doc_ids.append(doc.id)

        if not requeued_doc_ids:
            raise ingestion_error("DOC_RETRY_NOT_ALLOWED")

        await self._recalculate_batch(batch, reason="manual_retry")
        await self._db.commit()
        self._enqueue_docs(requeued_doc_ids)

        return IngestionBatchRetryResponse(
            batch_id=batch.id,
            status=BatchStatus(batch.status.value),
            requeued_docs=len(requeued_doc_ids),
            ignored_docs=ignored_docs,
        )

    async def cancel_batch(self, *, batch_id: uuid.UUID) -> IngestionBatchCancelResponse:
        batch = await self._get_batch_or_raise(batch_id=batch_id, for_update=True)
        if batch.status not in {IngestionBatchStatus.QUEUED, IngestionBatchStatus.RUNNING}:
            raise ingestion_error("BATCH_STATUS_CONFLICT", details={"status": batch.status.value})

        canceled_docs = 0
        for doc in list(batch.docs):
            if doc.status in {IngestionDocStatus.PENDING, IngestionDocStatus.RUNNING}:
                await self._set_doc_status(doc, IngestionDocStatus.CANCELED, reason="batch_cancel")
                canceled_docs += 1

        await self._recalculate_batch(batch, reason="batch_cancel")
        await self._db.commit()

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

    async def mark_doc_running(self, *, doc: IngestionBatchDoc) -> None:
        if doc.retry_count >= MAX_DOC_ATTEMPTS:
            raise ingestion_error(
                "DOC_RETRY_LIMIT_REACHED",
                details={"doc_id": str(doc.id), "retry_count": doc.retry_count},
            )

        if doc.status not in {
            IngestionDocStatus.PENDING,
            IngestionDocStatus.FAILED,
            IngestionDocStatus.RUNNING,
        }:
            raise ingestion_error(
                "DOC_RETRY_NOT_ALLOWED",
                details={"doc_id": str(doc.id), "status": doc.status.value},
            )

        doc.retry_count += 1
        await self._set_doc_status(doc, IngestionDocStatus.RUNNING, reason="doc_start")
        doc.retryable = doc.retry_count < MAX_DOC_ATTEMPTS

    async def mark_doc_succeeded(self, *, doc: IngestionBatchDoc, chunk_count: int) -> None:
        doc.chunk_count = max(chunk_count, 0)
        doc.retryable = False
        doc.error_code = None
        doc.error_message = None
        await self._set_doc_status(doc, IngestionDocStatus.SUCCEEDED, reason="doc_succeeded")

    async def mark_doc_failed(
        self,
        *,
        doc: IngestionBatchDoc,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> int | None:
        auto_retry_delay: int | None = None
        auto_retryable = retryable and doc.retry_count <= len(AUTO_RETRY_DELAYS)
        within_attempt_limit = doc.retry_count < MAX_DOC_ATTEMPTS

        if auto_retryable and within_attempt_limit:
            delay = AUTO_RETRY_DELAYS[doc.retry_count - 1]
            doc.retryable = True
            doc.error_code = error_code
            doc.error_message = error_message
            await self._set_doc_status(doc, IngestionDocStatus.PENDING, reason="auto_retry")
            auto_retry_delay = delay
        else:
            doc.retryable = retryable and within_attempt_limit
            doc.error_code = error_code
            doc.error_message = error_message
            await self._set_doc_status(doc, IngestionDocStatus.FAILED, reason="doc_failed")

        return auto_retry_delay

    async def recalculate_batch_for_doc(self, *, doc: IngestionBatchDoc, reason: str) -> None:
        batch = await self._get_batch_or_raise(batch_id=doc.batch_id, for_update=True)
        await self._recalculate_batch(batch, reason=reason)

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()

    async def _create_batch_with_retry(
        self,
        *,
        kb_id: uuid.UUID,
        prepared_entries: list[_PreparedEntry],
        requested_by: str | None,
    ) -> tuple[IngestionBatch, list[IngestionBatchDoc]]:
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update()
        kb = (await self._db.execute(stmt)).scalar_one_or_none()
        if kb is None:
            raise ingestion_error("KB_NOT_FOUND")

        snapshot = await self._ensure_current_snapshot(kb=kb)

        bootstrap_stmt = (
            select(IngestionBatch.id)
            .where(IngestionBatch.kb_id == kb.id, IngestionBatch.is_bootstrap.is_(True))
            .limit(1)
        )
        has_bootstrap = (await self._db.execute(bootstrap_stmt)).scalar_one_or_none() is not None

        batch = IngestionBatch(
            kb_id=kb.id,
            config_snapshot_id=snapshot.id,
            config_version=kb.current_config_version,
            is_bootstrap=not has_bootstrap,
            status=IngestionBatchStatus.QUEUED,
            requested_by=requested_by,
            total_docs=len(prepared_entries),
            progress_percent=0,
        )
        self._db.add(batch)
        await self._db.flush()

        docs: list[IngestionBatchDoc] = []
        for prepared in prepared_entries:
            material_id = await self._materialize_source_material(kb_id=kb.id, prepared=prepared)
            doc = IngestionBatchDoc(
                batch_id=batch.id,
                kb_id=kb.id,
                config_snapshot_id=snapshot.id,
                config_version=kb.current_config_version,
                source_type=IngestionSourceType(prepared.source_type.value),
                source_ref=str(material_id),
                title=prepared.title,
                fingerprint=prepared.fingerprint,
                status=IngestionDocStatus.PENDING,
                retry_count=0,
                retryable=True,
            )
            self._db.add(doc)
            docs.append(doc)

        await self._db.flush()
        await self._append_event(
            batch_id=batch.id,
            doc_id=None,
            from_status=None,
            to_status=batch.status.value,
            reason="batch_created",
        )
        await self._db.commit()

        await self._db.refresh(batch)
        for doc in docs:
            await self._db.refresh(doc)
        return batch, docs

    async def _prepare_entries(
        self,
        *,
        kb: KnowledgeBase,
        entries: list[ManifestEntry],
        entry_errors: list[EntryErrorRead],
    ) -> list[_PreparedEntry]:
        prepared_entries: list[_PreparedEntry] = []
        fingerprints_seen: set[str] = set()
        url_count = 0
        file_count = 0

        for idx, entry in enumerate(entries, start=1):
            entry_id = (getattr(entry, "entry_id", None) or f"entry_{idx}").strip() or f"entry_{idx}"
            source_type = ManifestSourceType(entry.source_type)

            try:
                if isinstance(entry, ManifestTextEntry):
                    prepared = await self._prepare_text_entry(kb=kb, entry=entry, entry_id=entry_id)
                elif isinstance(entry, ManifestUrlEntry):
                    url_count += 1
                    if url_count > MAX_URL_ENTRIES:
                        raise ingestion_error("MANIFEST_LIMIT_EXCEEDED", details={"max_url_entries": MAX_URL_ENTRIES})
                    prepared = await self._prepare_url_entry(kb=kb, entry=entry, entry_id=entry_id)
                elif isinstance(entry, ManifestFileEntry):
                    file_count += 1
                    if file_count > MAX_FILE_ENTRIES:
                        raise ingestion_error("MANIFEST_LIMIT_EXCEEDED", details={"max_file_entries": MAX_FILE_ENTRIES})
                    prepared = await self._prepare_file_entry(kb=kb, entry=entry, entry_id=entry_id)
                else:  # pragma: no cover
                    raise ingestion_error("MANIFEST_ALL_ENTRIES_FAILED")
            except AppError as exc:
                entry_errors.append(self._entry_error_from_app_error(entry_id=entry_id, source_type=source_type, exc=exc))
                continue

            if prepared.fingerprint in fingerprints_seen:
                entry_errors.append(
                    EntryErrorRead(
                        entry_id=entry_id,
                        source_type=prepared.source_type,
                        code="IDEMPOTENCY_DUPLICATE",
                        message=INGESTION_ERROR_SPECS["IDEMPOTENCY_DUPLICATE"].message,
                        retryable=False,
                        details={"duplicate_scope": "manifest"},
                    )
                )
                continue

            dup_stmt = (
                select(IngestionBatchDoc.id)
                .where(
                    IngestionBatchDoc.kb_id == kb.id,
                    IngestionBatchDoc.config_version == kb.current_config_version,
                    IngestionBatchDoc.fingerprint == prepared.fingerprint,
                )
                .limit(1)
            )
            duplicate_doc_id = (await self._db.execute(dup_stmt)).scalar_one_or_none()
            if duplicate_doc_id is not None:
                entry_errors.append(
                    EntryErrorRead(
                        entry_id=entry_id,
                        source_type=prepared.source_type,
                        code="IDEMPOTENCY_DUPLICATE",
                        message=INGESTION_ERROR_SPECS["IDEMPOTENCY_DUPLICATE"].message,
                        retryable=False,
                        details={"duplicate_doc_id": str(duplicate_doc_id)},
                    )
                )
                continue

            fingerprints_seen.add(prepared.fingerprint)
            prepared_entries.append(prepared)

        return prepared_entries

    async def _prepare_text_entry(
        self,
        *,
        kb: KnowledgeBase,
        entry: ManifestTextEntry,
        entry_id: str,
    ) -> _PreparedEntry:
        normalized = "\n".join(line.strip() for line in entry.text.splitlines()).strip()
        if not normalized or len(normalized) > MAX_TEXT_LENGTH:
            raise ingestion_error(
                "TEXT_LENGTH_INVALID",
                details={"length": len(normalized), "max_length": MAX_TEXT_LENGTH},
            )

        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return _PreparedEntry(
            entry_id=entry_id,
            source_type=ManifestSourceType.TEXT,
            title=entry.title or "文本条目",
            payload={"text": normalized},
            fingerprint=fingerprint,
        )

    async def _prepare_url_entry(
        self,
        *,
        kb: KnowledgeBase,
        entry: ManifestUrlEntry,
        entry_id: str,
    ) -> _PreparedEntry:
        canonical_url = self._canonicalize_url(entry.url)
        parsed = urlparse(canonical_url)
        if parsed.scheme not in {"http", "https"}:
            raise ingestion_error("URL_SCHEME_NOT_ALLOWED", details={"url": entry.url})

        async with httpx.AsyncClient(timeout=MAX_URL_TIMEOUT_SECONDS) as client:
            final_url = await self._validate_url_security(url=canonical_url, client=client)

        fingerprint = hashlib.sha256(final_url.encode("utf-8")).hexdigest()
        return _PreparedEntry(
            entry_id=entry_id,
            source_type=ManifestSourceType.URL,
            title=entry.title or final_url,
            payload={"url": final_url},
            fingerprint=fingerprint,
        )

    async def _prepare_file_entry(
        self,
        *,
        kb: KnowledgeBase,
        entry: ManifestFileEntry,
        entry_id: str,
    ) -> _PreparedEntry:
        material = await self._db.get(SourceMaterial, entry.material_id)
        if material is None or material.kb_id != kb.id:
            raise ingestion_error(
                "KB_NOT_FOUND",
                message="文件条目引用的资料不存在或不属于当前知识库",
                details={"material_id": str(entry.material_id)},
            )

        if material.source_type != SourceType.UPLOAD:
            raise ingestion_error(
                "FILE_TYPE_NOT_ALLOWED",
                details={"material_id": str(entry.material_id), "reason": "not_upload"},
            )

        ext = self._material_extension(material)
        if ext not in ALLOWED_FILE_EXTENSIONS:
            raise ingestion_error(
                "FILE_TYPE_NOT_ALLOWED",
                details={"material_id": str(entry.material_id), "extension": ext},
            )

        size = await self._material_file_size(material)
        if size is not None and size > MAX_FILE_SIZE_BYTES:
            raise ingestion_error(
                "FILE_SIZE_EXCEEDED",
                details={"material_id": str(entry.material_id), "size": size, "max_size": MAX_FILE_SIZE_BYTES},
            )

        base = material.content_hash or str(material.id)
        fingerprint = hashlib.sha256(base.encode("utf-8")).hexdigest()

        return _PreparedEntry(
            entry_id=entry_id,
            source_type=ManifestSourceType.FILE,
            title=entry.title or material.title,
            payload={"material_id": str(material.id)},
            fingerprint=fingerprint,
        )

    async def _materialize_source_material(
        self,
        *,
        kb_id: uuid.UUID,
        prepared: _PreparedEntry,
    ) -> uuid.UUID:
        if prepared.source_type == ManifestSourceType.TEXT:
            text = str(prepared.payload["text"])
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
            material = SourceMaterial(
                kb_id=kb_id,
                source_type=SourceType.TEXT,
                title=prepared.title or "文本条目",
                content_hash=content_hash,
                metadata_={"text": text},
            )
            self._db.add(material)
            await self._db.flush()
            return material.id

        if prepared.source_type == ManifestSourceType.URL:
            url = str(prepared.payload["url"])
            content_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            material = SourceMaterial(
                kb_id=kb_id,
                source_type=SourceType.URL,
                title=prepared.title or url,
                uri=url,
                content_hash=content_hash,
            )
            self._db.add(material)
            await self._db.flush()
            return material.id

        return uuid.UUID(str(prepared.payload["material_id"]))

    async def _ensure_current_snapshot(self, *, kb: KnowledgeBase) -> KBConfigSnapshot:
        stmt = (
            select(KBConfigSnapshot)
            .where(
                KBConfigSnapshot.kb_id == kb.id,
                KBConfigSnapshot.version == kb.current_config_version,
            )
            .limit(1)
        )
        snapshot = (await self._db.execute(stmt)).scalar_one_or_none()
        if snapshot is not None:
            return snapshot

        snapshot = KBConfigSnapshot(
            kb_id=kb.id,
            version=kb.current_config_version,
            config_json=kb.index_config or {},
        )
        self._db.add(snapshot)
        await self._db.flush()
        return snapshot

    def _enqueue_docs(self, doc_ids: list[uuid.UUID]) -> None:
        if not doc_ids:
            return

        from app.worker.tasks.ingestion_batches import run_ingestion_batch_doc

        for doc_id in doc_ids:
            run_ingestion_batch_doc.delay(str(doc_id))

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
            raise ingestion_error("BATCH_NOT_FOUND", details={"batch_id": str(batch_id)})
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
            IngestionDocStatus.PENDING: {IngestionDocStatus.RUNNING, IngestionDocStatus.CANCELED},
            IngestionDocStatus.RUNNING: {
                IngestionDocStatus.SUCCEEDED,
                IngestionDocStatus.FAILED,
                IngestionDocStatus.CANCELED,
                IngestionDocStatus.PENDING,
            },
            IngestionDocStatus.FAILED: {IngestionDocStatus.PENDING},
            IngestionDocStatus.SUCCEEDED: set(),
            IngestionDocStatus.CANCELED: set(),
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
                IngestionBatchStatus.RUNNING,
                IngestionBatchStatus.CANCELED,
                IngestionBatchStatus.SUCCEEDED,
                IngestionBatchStatus.PARTIAL_FAILED,
                IngestionBatchStatus.FAILED,
            },
            IngestionBatchStatus.RUNNING: {
                IngestionBatchStatus.QUEUED,
                IngestionBatchStatus.CANCELED,
                IngestionBatchStatus.SUCCEEDED,
                IngestionBatchStatus.PARTIAL_FAILED,
                IngestionBatchStatus.FAILED,
            },
            IngestionBatchStatus.SUCCEEDED: {IngestionBatchStatus.QUEUED, IngestionBatchStatus.RUNNING},
            IngestionBatchStatus.PARTIAL_FAILED: {IngestionBatchStatus.QUEUED, IngestionBatchStatus.RUNNING},
            IngestionBatchStatus.FAILED: {IngestionBatchStatus.QUEUED, IngestionBatchStatus.RUNNING},
            IngestionBatchStatus.CANCELED: {IngestionBatchStatus.QUEUED, IngestionBatchStatus.RUNNING},
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
        terminal = {
            IngestionBatchStatus.SUCCEEDED,
            IngestionBatchStatus.PARTIAL_FAILED,
            IngestionBatchStatus.FAILED,
            IngestionBatchStatus.CANCELED,
        }
        if new_status == IngestionBatchStatus.RUNNING and batch.started_at is None:
            batch.started_at = now
        if new_status in terminal:
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

    async def _recalculate_batch(self, batch: IngestionBatch, *, reason: str) -> None:
        docs = list(batch.docs)
        total = len(docs)
        succeeded = sum(1 for doc in docs if doc.status == IngestionDocStatus.SUCCEEDED)
        failed = sum(1 for doc in docs if doc.status == IngestionDocStatus.FAILED)
        canceled = sum(1 for doc in docs if doc.status == IngestionDocStatus.CANCELED)
        running = sum(1 for doc in docs if doc.status == IngestionDocStatus.RUNNING)
        pending = sum(1 for doc in docs if doc.status == IngestionDocStatus.PENDING)

        batch.total_docs = total
        batch.succeeded_docs = succeeded
        batch.failed_docs = failed
        batch.canceled_docs = canceled
        batch.succeeded_chunks = sum(doc.chunk_count for doc in docs if doc.status == IngestionDocStatus.SUCCEEDED)

        completed = succeeded + failed + canceled
        batch.progress_percent = math.floor((completed / total) * 100) if total else 0

        terminal = completed == total
        if terminal:
            if succeeded == total:
                target_status = IngestionBatchStatus.SUCCEEDED
            elif succeeded > 0:
                target_status = IngestionBatchStatus.PARTIAL_FAILED
            elif canceled > 0:
                target_status = IngestionBatchStatus.CANCELED
            else:
                target_status = IngestionBatchStatus.FAILED
        elif running > 0:
            target_status = IngestionBatchStatus.RUNNING
        elif pending > 0:
            target_status = IngestionBatchStatus.QUEUED
        else:
            target_status = IngestionBatchStatus.RUNNING

        await self._set_batch_status(batch, target_status, reason=reason)
        if terminal:
            await self._apply_readiness(batch=batch)

        batch.error_summary = {
            "succeeded_docs": succeeded,
            "failed_docs": failed,
            "canceled_docs": canceled,
            "reason": reason,
        }

    async def _apply_readiness(self, *, batch: IngestionBatch) -> None:
        kb = await self._db.get(KnowledgeBase, batch.kb_id)
        if kb is None:
            return

        if batch.is_bootstrap:
            terminal = {
                IngestionBatchStatus.SUCCEEDED,
                IngestionBatchStatus.PARTIAL_FAILED,
                IngestionBatchStatus.FAILED,
                IngestionBatchStatus.CANCELED,
            }
            if batch.status in terminal and batch.succeeded_docs >= 1 and batch.succeeded_chunks >= 1:
                kb.readiness = KnowledgeBaseReadiness.READY
            else:
                kb.readiness = KnowledgeBaseReadiness.NOT_READY
            kb.readiness_updated_at = datetime.now(timezone.utc)

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

    async def _get_event_count(self, *, batch_id: uuid.UUID) -> int:
        stmt = select(func.count(IngestionEvent.id)).where(IngestionEvent.batch_id == batch_id)
        result = await self._db.execute(stmt)
        value = result.scalar_one()
        return int(value or 0)

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
            batch.progress_percent,
            batch.succeeded_docs,
            batch.failed_docs,
            batch.canceled_docs,
            batch.succeeded_chunks,
            batch.finished_at.isoformat() if batch.finished_at else "",
            doc_states,
        )

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))

    async def _validate_url_security(self, *, url: str, client: httpx.AsyncClient) -> str:
        current = url
        for redirect_hops in range(MAX_URL_REDIRECTS + 1):
            parsed = urlparse(current)
            host = parsed.hostname
            if not host:
                raise ingestion_error("URL_SCHEME_NOT_ALLOWED", details={"url": current})

            await self._assert_host_safe(host)

            if redirect_hops == MAX_URL_REDIRECTS:
                break

            try:
                response = await client.get(current, follow_redirects=False)
            except Exception as exc:
                raise ingestion_error(
                    "URL_SSRF_BLOCKED",
                    message="URL 安全探测失败",
                    details={"url": current, "reason": str(exc), "retryable": True},
                ) from exc

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    break
                current = self._canonicalize_url(urljoin(current, location))
                continue
            break

        return current

    async def _assert_host_safe(self, host: str) -> None:
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            ips = await anyio.to_thread.run_sync(self._resolve_host_ips, host)

        if not ips:
            raise ingestion_error("URL_SSRF_BLOCKED", details={"host": host, "reason": "unresolvable"})

        for ip in ips:
            if self._is_blocked_ip(ip):
                raise ingestion_error("URL_SSRF_BLOCKED", details={"host": host, "blocked_ip": str(ip)})

    @staticmethod
    def _resolve_host_ips(host: str) -> list[ipaddress._BaseAddress]:
        addresses: list[ipaddress._BaseAddress] = []
        for info in socket.getaddrinfo(host, None):
            raw = info[4][0]
            try:
                addresses.append(ipaddress.ip_address(raw))
            except ValueError:
                continue
        uniq = {str(ip): ip for ip in addresses}
        return list(uniq.values())

    @staticmethod
    def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
        if ip in _URL_BLOCKED_IPV4:
            return True
        return (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    @staticmethod
    def _entry_error_from_app_error(
        *,
        entry_id: str,
        source_type: ManifestSourceType,
        exc: AppError,
    ) -> EntryErrorRead:
        details = dict(exc.details or {})
        retryable = bool(details.pop("retryable", False))
        return EntryErrorRead(
            entry_id=entry_id,
            source_type=source_type,
            code=exc.code,
            message=exc.message,
            retryable=retryable,
            details=details or None,
        )

    @staticmethod
    def _material_extension(material: SourceMaterial) -> str:
        uri = material.uri or ""
        filename = uri.rsplit("/", 1)[-1]
        if "." not in filename:
            return ""
        return "." + filename.rsplit(".", 1)[-1].lower()

    async def _material_file_size(self, material: SourceMaterial) -> int | None:
        uri = material.uri or ""
        if not uri.startswith("minio://"):
            return None

        raw = uri[len("minio://") :]
        if "/" not in raw:
            return None
        bucket, object_name = raw.split("/", 1)
        if not bucket or not object_name:
            return None

        storage = ObjectStorage()
        try:
            return await storage.get_size(ObjectRef(bucket=bucket, object_name=object_name))
        except Exception:
            return None

    @staticmethod
    def _is_bootstrap_conflict(exc: IntegrityError) -> bool:
        orig = getattr(exc, "orig", None)
        message = str(orig or exc).lower()
        return "uq_ingestion_batches_bootstrap_kb" in message or "is_bootstrap" in message
