from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError

from app.integrations.object_storage import ObjectRef, ObjectStorage
from app.models.ingestion_batch import (
    IngestionBatch,
    IngestionBatchDoc,
    IngestionBatchStatus,
    IngestionDocStatus,
    IngestionSourceType,
)
from app.models.ingestion_task_outbox import IngestionTaskOutbox, IngestionTaskOutboxStatus
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial, SourceType
from app.schemas.ingestion_batches import (
    EntryErrorRead,
    ManifestEntry,
    ManifestFileEntry,
    ManifestSourceType,
    ManifestTextEntry,
    ManifestUrlEntry,
)
from app.services.ingestion_batch_service_contracts import (
    ALLOWED_FILE_EXTENSIONS,
    INGESTION_DOC_TASK_NAME,
    MAX_FILE_ENTRIES,
    MAX_FILE_SIZE_BYTES,
    MAX_TEXT_LENGTH,
    MAX_URL_ENTRIES,
    _PreparedEntry,
)
from app.services.ingestion_contract import INGESTION_ERROR_SPECS, ingestion_error

logger = logging.getLogger(__name__)


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
    has_bootstrap = (
        await self._db.execute(bootstrap_stmt)
    ).scalar_one_or_none() is not None

    batch = IngestionBatch(
        kb_id=kb.id,
        config_snapshot_id=snapshot.id,
        config_version=kb.current_config_version,
        is_bootstrap=not has_bootstrap,
        status=IngestionBatchStatus.QUEUED,
        requested_by=requested_by,
        total_docs=len(prepared_entries),
    )
    self._db.add(batch)
    await self._db.flush()

    docs: list[IngestionBatchDoc] = []
    for prepared in prepared_entries:
        material_id = await self._materialize_source_material(
            kb_id=kb.id, prepared=prepared
        )
        doc = IngestionBatchDoc(
            batch_id=batch.id,
            kb_id=kb.id,
            config_snapshot_id=snapshot.id,
            config_version=kb.current_config_version,
            source_type=IngestionSourceType(prepared.source_type.value),
            source_ref=str(material_id),
            title=prepared.title,
            fingerprint=prepared.fingerprint,
            status=IngestionDocStatus.QUEUED,
            retry_count=0,
            retryable=True,
            context_failed_chunks=None,
        )
        self._db.add(doc)
        docs.append(doc)

    await self._db.flush()
    for doc in docs:
        self._db.add(
            IngestionTaskOutbox(
                doc_id=doc.id,
                batch_id=batch.id,
                task_name=INGESTION_DOC_TASK_NAME,
                payload={"doc_id": str(doc.id)},
                status=IngestionTaskOutboxStatus.PENDING,
                attempts=0,
                max_attempts=20,
                next_retry_at=None,
                dispatched_at=None,
                last_error=None,
            )
        )
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
    prepared_candidates: list[_PreparedEntry] = []
    fingerprints_seen: set[str] = set()
    url_count = 0
    file_count = 0

    for idx, entry in enumerate(entries, start=1):
        entry_id = (
            getattr(entry, "entry_id", None) or f"entry_{idx}"
        ).strip() or f"entry_{idx}"
        source_type = ManifestSourceType(entry.source_type)

        try:
            if isinstance(entry, ManifestTextEntry):
                prepared = await self._prepare_text_entry(
                    kb=kb, entry=entry, entry_id=entry_id
                )
            elif isinstance(entry, ManifestUrlEntry):
                url_count += 1
                if url_count > MAX_URL_ENTRIES:
                    raise ingestion_error(
                        "MANIFEST_LIMIT_EXCEEDED",
                        details={"max_url_entries": MAX_URL_ENTRIES},
                    )
                prepared = await self._prepare_url_entry(
                    kb=kb, entry=entry, entry_id=entry_id
                )
            elif isinstance(entry, ManifestFileEntry):
                file_count += 1
                if file_count > MAX_FILE_ENTRIES:
                    raise ingestion_error(
                        "MANIFEST_LIMIT_EXCEEDED",
                        details={"max_file_entries": MAX_FILE_ENTRIES},
                    )
                prepared = await self._prepare_file_entry(
                    kb=kb, entry=entry, entry_id=entry_id
                )
            else:  # pragma: no cover
                raise ingestion_error("MANIFEST_ALL_ENTRIES_FAILED")
        except AppError as exc:
            entry_errors.append(
                self._entry_error_from_app_error(
                    entry_id=entry_id, source_type=source_type, exc=exc
                )
            )
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

        fingerprints_seen.add(prepared.fingerprint)
        prepared_candidates.append(prepared)

    if not prepared_candidates:
        return []

    fingerprints = [prepared.fingerprint for prepared in prepared_candidates]
    dup_stmt = select(IngestionBatchDoc.id, IngestionBatchDoc.fingerprint).where(
        IngestionBatchDoc.kb_id == kb.id,
        IngestionBatchDoc.config_version == kb.current_config_version,
        IngestionBatchDoc.fingerprint.in_(fingerprints),
    )
    duplicate_by_fingerprint = {
        fingerprint: doc_id
        for doc_id, fingerprint in (await self._db.execute(dup_stmt)).all()
    }

    prepared_entries: list[_PreparedEntry] = []
    for prepared in prepared_candidates:
        duplicate_doc_id = duplicate_by_fingerprint.get(prepared.fingerprint)
        if duplicate_doc_id is not None:
            entry_errors.append(
                EntryErrorRead(
                    entry_id=prepared.entry_id,
                    source_type=prepared.source_type,
                    code="IDEMPOTENCY_DUPLICATE",
                    message=INGESTION_ERROR_SPECS["IDEMPOTENCY_DUPLICATE"].message,
                    retryable=False,
                    details={"duplicate_doc_id": str(duplicate_doc_id)},
                )
            )
            continue

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
    del kb
    final_url = await self._url_guard.validate_source_url(entry.url)

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
            details={
                "material_id": str(entry.material_id),
                "size": size,
                "max_size": MAX_FILE_SIZE_BYTES,
            },
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
            id=uuid.uuid4(),
            kb_id=kb_id,
            source_type=SourceType.TEXT,
            title=prepared.title or "文本条目",
            content_hash=content_hash,
            metadata_={"text": text},
        )
        self._db.add(material)
        return material.id

    if prepared.source_type == ManifestSourceType.URL:
        url = str(prepared.payload["url"])
        content_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        material = SourceMaterial(
            id=uuid.uuid4(),
            kb_id=kb_id,
            source_type=SourceType.URL,
            title=prepared.title or url,
            uri=url,
            content_hash=content_hash,
        )
        self._db.add(material)
        return material.id

    return uuid.UUID(str(prepared.payload["material_id"]))


async def _ensure_current_snapshot(self, *, kb: KnowledgeBase) -> KBConfigSnapshot:
    active_stmt = (
        select(KBConfigSnapshot)
        .where(
            KBConfigSnapshot.kb_id == kb.id,
            KBConfigSnapshot.is_active.is_(True),
        )
        .order_by(KBConfigSnapshot.version.desc())
        .limit(1)
    )
    snapshot = (await self._db.execute(active_stmt)).scalar_one_or_none()
    if snapshot is not None:
        if kb.current_config_version != snapshot.version:
            kb.current_config_version = snapshot.version
        if (kb.index_config or {}) != (snapshot.config_json or {}):
            kb.index_config = snapshot.config_json or {}
        return snapshot

    max_version_stmt = select(func.max(KBConfigSnapshot.version)).where(
        KBConfigSnapshot.kb_id == kb.id
    )
    max_version = (await self._db.execute(max_version_stmt)).scalar_one()
    next_version = int(max_version or kb.current_config_version or 0)
    next_version = max(next_version, 1)

    snapshot = KBConfigSnapshot(
        kb_id=kb.id,
        version=next_version,
        config_json=kb.index_config or {},
        is_active=True,
    )
    kb.current_config_version = next_version
    self._db.add(snapshot)
    await self._db.flush()
    return snapshot


async def _ensure_outbox_for_docs(
    self,
    *,
    doc_ids: list[uuid.UUID],
    batch_id: uuid.UUID,
) -> None:
    if not doc_ids:
        return

    stmt = (
        select(IngestionTaskOutbox)
        .where(
            IngestionTaskOutbox.doc_id.in_(doc_ids),
            IngestionTaskOutbox.task_name == INGESTION_DOC_TASK_NAME,
        )
        .with_for_update()
    )
    existing = list((await self._db.execute(stmt)).scalars().all())
    existing_by_doc_id = {row.doc_id: row for row in existing}

    for doc_id in doc_ids:
        row = existing_by_doc_id.get(doc_id)
        if row is None:
            self._db.add(
                IngestionTaskOutbox(
                    doc_id=doc_id,
                    batch_id=batch_id,
                    task_name=INGESTION_DOC_TASK_NAME,
                    payload={"doc_id": str(doc_id)},
                    status=IngestionTaskOutboxStatus.PENDING,
                    attempts=0,
                    max_attempts=20,
                    next_retry_at=None,
                    dispatched_at=None,
                    last_error=None,
                )
            )
            continue

        row.batch_id = batch_id
        row.payload = {"doc_id": str(doc_id)}
        row.status = IngestionTaskOutboxStatus.PENDING
        row.attempts = 0
        row.next_retry_at = None
        row.dispatched_at = None
        row.last_error = None


def _trigger_outbox_dispatch(self) -> None:
    try:
        from app.worker.tasks.ingestion_outbox_dispatcher import (
            dispatch_ingestion_outbox,
        )

        dispatch_ingestion_outbox.delay()
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "Failed to trigger ingestion outbox dispatcher",
            extra={"error": str(exc)},
        )




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
        return await storage.get_size(
            ObjectRef(bucket=bucket, object_name=object_name)
        )
    except Exception:
        return None


def _is_bootstrap_conflict(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    message = str(orig or exc).lower()
    return (
        "uq_ingestion_batches_bootstrap_kb" in message or "is_bootstrap" in message
    )
