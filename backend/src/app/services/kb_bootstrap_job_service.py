from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import Celery
import httpx
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.settings import get_settings
from app.services.upload_policy import (
    ALLOWED_UPLOAD_EXTENSIONS,
    ALLOWED_UPLOAD_MIME_TYPES,
    GENERIC_UPLOAD_MIME_TYPES,
    MAX_UPLOAD_FILE_SIZE_BYTES,
    normalize_upload_content_type,
)
from app.integrations.object_storage import ObjectRef, ObjectStorage
from app.models.kb_bootstrap_job import KBBootstrapJob, KBBootstrapJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial, SourceType
from app.schemas.ingestion_batches import (
    IngestionBatchSubmitResponse,
    ManifestEntry,
    ManifestFileEntry,
    ManifestSourceType,
)
from app.schemas.kb_bootstrap_jobs import (
    BootstrapManifestEntry,
    BootstrapManifestTextEntry,
    BootstrapManifestUrlEntry,
    BootstrapSubmissionCreateRequest,
    BootstrapSubmissionUploadProgress,
    BootstrapUploadTarget,
)
from app.services.ingestion_batch_service import IngestionBatchService
from app.worker.celery_app import celery_app


@dataclass(slots=True)
class BootstrapSubmissionCreateResult:
    job: KBBootstrapJob | None
    batch: IngestionBatchSubmitResponse | None
    upload_targets: list[BootstrapUploadTarget]
    upload_progress: BootstrapSubmissionUploadProgress


@dataclass(slots=True)
class BootstrapUploadSessionResult:
    job: KBBootstrapJob
    upload_targets: list[BootstrapUploadTarget]
    upload_progress: BootstrapSubmissionUploadProgress


class KBBootstrapJobService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        celery: Celery | None = None,
        http_client: httpx.AsyncClient | None = None,
        object_storage: ObjectStorage,
    ) -> None:
        self._db = db
        self._celery = celery or celery_app
        self._http_client = http_client
        self._settings = get_settings()
        self._storage = object_storage

    async def create_submission(
        self,
        *,
        req: BootstrapSubmissionCreateRequest,
        request_id: str | None,
        requested_by: str | None,
    ) -> BootstrapSubmissionCreateResult:
        normalized_request_id = (request_id or "").strip()[:128] or None
        normalized_requested_by = (requested_by or "").strip()[:128] or None

        if normalized_request_id:
            existing = await self._get_by_request_id(normalized_request_id)
            if existing is not None:
                return BootstrapSubmissionCreateResult(
                    job=existing,
                    batch=None,
                    upload_targets=[],
                    upload_progress=self.get_upload_progress(existing),
                )

        kb = await self._db.get(KnowledgeBase, req.kb_id)
        if kb is None:
            raise AppError(code="KB_NOT_FOUND", message="知识库不存在", status_code=404)

        payload_entries, upload_manifest = await self._normalize_payload_entries(
            kb=kb, entries=req.entries
        )
        has_pending_uploads = len(upload_manifest) > 0
        if not has_pending_uploads:
            batch = await self._submit_manifest_directly(
                kb_id=req.kb_id,
                payload_entries=payload_entries,
                requested_by=normalized_requested_by,
            )
            return BootstrapSubmissionCreateResult(
                job=None,
                batch=batch,
                upload_targets=[],
                upload_progress=BootstrapSubmissionUploadProgress(),
            )

        job = KBBootstrapJob(
            kb_id=req.kb_id,
            request_id=normalized_request_id,
            requested_by=normalized_requested_by,
            status=KBBootstrapJobStatus.QUEUED_UPLOAD,
            total_entries=len(payload_entries),
            accepted_entries=0,
            failed_entries=0,
            payload_entries=payload_entries,
            upload_manifest=upload_manifest,
            progress_message="等待文件上传完成",
        )
        self._db.add(job)

        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            if normalized_request_id:
                existing = await self._get_by_request_id(normalized_request_id)
                if existing is not None:
                    return BootstrapSubmissionCreateResult(
                        job=existing,
                        batch=None,
                        upload_targets=[],
                        upload_progress=self.get_upload_progress(existing),
                    )
            raise

        await self._db.refresh(job)

        return BootstrapSubmissionCreateResult(
            job=job,
            batch=None,
            upload_targets=[],
            upload_progress=self.get_upload_progress(job),
        )

    async def create_upload_session(
        self, *, job_id: uuid.UUID
    ) -> BootstrapUploadSessionResult:
        job = await self._db.get(KBBootstrapJob, job_id)
        if job is None:
            raise AppError(
                code="KB_BOOTSTRAP_JOB_NOT_FOUND", message="任务不存在", status_code=404
            )
        if job.status != KBBootstrapJobStatus.QUEUED_UPLOAD:
            raise AppError(
                code="KB_BOOTSTRAP_UPLOAD_SESSION_NOT_ALLOWED",
                message="当前任务状态不允许创建上传会话",
                status_code=409,
            )

        upload_targets = await self._build_upload_targets(job)
        return BootstrapUploadSessionResult(
            job=job,
            upload_targets=upload_targets,
            upload_progress=self.get_upload_progress(job),
        )

    async def finalize_submission(self, *, job_id: uuid.UUID) -> KBBootstrapJob:
        job = await self._db.get(KBBootstrapJob, job_id)
        if job is None:
            raise AppError(
                code="KB_BOOTSTRAP_JOB_NOT_FOUND", message="任务不存在", status_code=404
            )

        if job.status in {KBBootstrapJobStatus.RUNNING, KBBootstrapJobStatus.COMPLETED}:
            return job

        upload_manifest = self._normalize_upload_manifest(job.upload_manifest)
        if not upload_manifest:
            return job

        if job.status == KBBootstrapJobStatus.FAILED:
            raise AppError(
                code="KB_BOOTSTRAP_JOB_TERMINAL",
                message="任务已失败，无法再次提交",
                status_code=409,
            )

        if job.status != KBBootstrapJobStatus.QUEUED_UPLOAD:
            return job

        checked_manifest, missing_entry_ids = await self._validate_upload_manifest(
            upload_manifest
        )

        locked_job = await self._get_submission_for_update(job_id)
        if locked_job is None:
            raise AppError(
                code="KB_BOOTSTRAP_JOB_NOT_FOUND", message="任务不存在", status_code=404
            )
        if locked_job.status in {
            KBBootstrapJobStatus.RUNNING,
            KBBootstrapJobStatus.COMPLETED,
        }:
            return locked_job
        if locked_job.status == KBBootstrapJobStatus.FAILED:
            raise AppError(
                code="KB_BOOTSTRAP_JOB_TERMINAL",
                message="任务已失败，无法再次提交",
                status_code=409,
            )
        if locked_job.status != KBBootstrapJobStatus.QUEUED_UPLOAD:
            return locked_job

        if missing_entry_ids:
            locked_job.upload_manifest = checked_manifest
            locked_job.progress_message = "存在未完成上传的文件，请重试失败文件后再提交"
            await self._db.commit()
            raise AppError(
                code="KB_BOOTSTRAP_UPLOAD_INCOMPLETE",
                message="部分文件尚未上传完成",
                status_code=409,
                details={"entry_ids": missing_entry_ids},
            )

        for item in checked_manifest:
            material_id = uuid.UUID(item["material_id"])
            material = await self._db.get(SourceMaterial, material_id)
            if material is not None:
                continue

            content_hash = self._material_content_hash(item)
            self._db.add(
                SourceMaterial(
                    id=material_id,
                    kb_id=locked_job.kb_id,
                    source_type=SourceType.UPLOAD,
                    title=item["title"],
                    uri=f"minio://{item['bucket']}/{item['object_key']}",
                    mime_type=item.get("content_type"),
                    content_hash=content_hash,
                )
            )

        locked_job.upload_manifest = checked_manifest
        locked_job.status = KBBootstrapJobStatus.RUNNING
        locked_job.progress_message = "正在校验并提交条目"
        if locked_job.started_at is None:
            locked_job.started_at = datetime.now(timezone.utc)

        try:
            response = await self._submit_manifest_directly(
                kb_id=locked_job.kb_id,
                payload_entries=locked_job.payload_entries or [],
                requested_by=locked_job.requested_by,
            )
            locked_job.batch_id = response.batch_id
            locked_job.status = KBBootstrapJobStatus.COMPLETED
            locked_job.accepted_entries = response.accepted_docs
            locked_job.failed_entries = response.failed_docs
            locked_job.entry_errors = [
                err.model_dump(mode="json") for err in response.entry_errors
            ]
            locked_job.error_code = None
            locked_job.error_message = None
            locked_job.progress_message = "批次已创建，文档处理中"
        except AppError as exc:
            await self._db.rollback()
            locked_job = await self._db.get(KBBootstrapJob, job_id)
            if locked_job is None:
                raise
            details = exc.details or {}
            entry_errors = details.get("entry_errors")
            locked_job.status = KBBootstrapJobStatus.FAILED
            locked_job.error_code = exc.code
            locked_job.error_message = exc.message
            locked_job.entry_errors = entry_errors if isinstance(entry_errors, list) else None
            locked_job.failed_entries = (
                len(entry_errors)
                if isinstance(entry_errors, list)
                else len(locked_job.payload_entries or [])
            )
            locked_job.progress_message = "任务失败"
        except Exception as exc:  # pragma: no cover - defensive guard
            await self._db.rollback()
            locked_job = await self._db.get(KBBootstrapJob, job_id)
            if locked_job is None:
                raise
            locked_job.status = KBBootstrapJobStatus.FAILED
            locked_job.error_code = "KB_BOOTSTRAP_JOB_FAILED"
            locked_job.error_message = str(exc)
            locked_job.failed_entries = len(locked_job.payload_entries or [])
            locked_job.progress_message = "任务失败"

        locked_job.finished_at = datetime.now(timezone.utc)
        await self._db.commit()
        await self._db.refresh(locked_job)
        return locked_job

    async def get_submission(self, *, job_id: uuid.UUID) -> KBBootstrapJob | None:
        return await self._db.get(KBBootstrapJob, job_id)

    async def build_upload_targets(
        self, *, job: KBBootstrapJob
    ) -> list[BootstrapUploadTarget]:
        return await self._build_upload_targets(job)

    def get_upload_progress(
        self, job: KBBootstrapJob
    ) -> BootstrapSubmissionUploadProgress:
        upload_manifest = self._normalize_upload_manifest(job.upload_manifest)
        total_files = len(upload_manifest)
        if total_files == 0:
            return BootstrapSubmissionUploadProgress()

        uploaded_files = 0
        failed_files = 0
        for item in upload_manifest:
            status = str(item.get("upload_status") or "")
            if status == "uploaded":
                uploaded_files += 1
            elif status in {"missing", "size_mismatch"}:
                failed_files += 1

        return BootstrapSubmissionUploadProgress(
            total_files=total_files,
            uploaded_files=uploaded_files,
            failed_files=failed_files,
        )

    async def _validate_upload_manifest(
        self,
        upload_manifest: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        checked_manifest = [item.copy() for item in upload_manifest]
        storage = self._get_storage()

        async def _check_item(item: dict[str, Any]) -> str | None:
            object_ref = ObjectRef(
                bucket=item["bucket"], object_name=item["object_key"]
            )
            exists = await storage.exists(object_ref)
            if not exists:
                item["upload_status"] = "missing"
                return str(item["entry_id"])

            expected_size = int(item.get("size_bytes") or 0)
            if expected_size > 0:
                actual_size = await storage.get_size(object_ref)
                if actual_size != expected_size:
                    item["upload_status"] = "size_mismatch"
                    return str(item["entry_id"])

            item["upload_status"] = "uploaded"
            return None

        missing_entry_ids = [
            entry_id
            for entry_id in await asyncio.gather(
                *(_check_item(item) for item in checked_manifest)
            )
            if entry_id is not None
        ]
        return checked_manifest, missing_entry_ids

    async def _get_by_request_id(self, request_id: str) -> KBBootstrapJob | None:
        stmt = select(KBBootstrapJob).where(KBBootstrapJob.request_id == request_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_submission_for_update(
        self, job_id: uuid.UUID
    ) -> KBBootstrapJob | None:
        stmt = (
            select(KBBootstrapJob).where(KBBootstrapJob.id == job_id).with_for_update()
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _submit_manifest_directly(
        self,
        *,
        kb_id: uuid.UUID,
        payload_entries: list[dict[str, Any]],
        requested_by: str | None,
    ) -> IngestionBatchSubmitResponse:
        try:
            entries = TypeAdapter(list[ManifestEntry]).validate_python(payload_entries)
        except Exception as exc:
            raise AppError(
                code="KB_BOOTSTRAP_PAYLOAD_INVALID",
                message=str(exc),
                status_code=500,
            ) from exc

        service = IngestionBatchService(
            self._db,
            http_client=self._http_client,
            object_storage=self._storage,
        )
        return await service.submit_manifest(
            kb_id=kb_id,
            entries=entries,
            requested_by=requested_by,
        )

    async def _normalize_payload_entries(
        self,
        *,
        kb: KnowledgeBase,
        entries: list[BootstrapManifestEntry],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized_entries: list[dict[str, Any]] = []
        upload_manifest: list[dict[str, Any]] = []
        used_entry_ids: set[str] = set()

        for index, entry in enumerate(entries):
            entry_id = self._ensure_unique_entry_id(
                self._normalize_entry_id(entry.entry_id, fallback=f"entry_{index + 1}"),
                used_entry_ids,
            )
            title = self._normalize_title(getattr(entry, "title", None))

            if isinstance(entry, BootstrapManifestTextEntry):
                normalized_entries.append(
                    {
                        "source_type": ManifestSourceType.TEXT.value,
                        "entry_id": entry_id,
                        "title": title,
                        "text": entry.text,
                    }
                )
                continue

            if isinstance(entry, BootstrapManifestUrlEntry):
                normalized_entries.append(
                    {
                        "source_type": ManifestSourceType.URL.value,
                        "entry_id": entry_id,
                        "title": title,
                        "url": entry.url,
                    }
                )
                continue

            file_name = self._sanitize_filename(entry.filename)
            extension = self._file_extension(file_name)
            self._validate_file_entry(
                kb=kb,
                extension=extension,
                file_size=entry.size_bytes,
                content_type=entry.content_type,
            )

            material_id = uuid.uuid4()
            object_ref = ObjectRef(
                bucket=self._settings.minio_bucket_uploads,
                object_name=f"{kb.id}/{material_id}/{file_name}",
            )
            upload_manifest.append(
                {
                    "entry_id": entry_id,
                    "title": title or file_name,
                    "filename": file_name,
                    "content_type": normalize_upload_content_type(entry.content_type),
                    "size_bytes": int(entry.size_bytes),
                    "sha256": (entry.sha256 or "").strip().lower() or None,
                    "material_id": str(material_id),
                    "bucket": object_ref.bucket,
                    "object_key": object_ref.object_name,
                    "upload_status": "pending",
                }
            )
            normalized_entries.append(
                ManifestFileEntry(
                    source_type=ManifestSourceType.FILE.value,
                    entry_id=entry_id,
                    title=title,
                    material_id=material_id,
                ).model_dump(mode="json")
            )

        return normalized_entries, upload_manifest

    async def _build_upload_targets(
        self, job: KBBootstrapJob
    ) -> list[BootstrapUploadTarget]:
        if job.status != KBBootstrapJobStatus.QUEUED_UPLOAD:
            return []

        upload_manifest = self._normalize_upload_manifest(job.upload_manifest)
        pending_manifest = [
            item
            for item in upload_manifest
            if str(item.get("upload_status") or "pending")
            in {"pending", "missing", "size_mismatch"}
        ]
        if not pending_manifest:
            return []

        expires_seconds = max(
            int(self._settings.bootstrap_upload_presign_expire_seconds), 60
        )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)

        storage = self._get_storage()
        await storage.ensure_buckets()

        async def _build_target(item: dict[str, Any]) -> BootstrapUploadTarget:
            ref = ObjectRef(bucket=item["bucket"], object_name=item["object_key"])
            upload_url = await storage.presign_put(ref, expires_seconds=expires_seconds)
            headers: dict[str, str] = {}
            content_type = str(item.get("content_type") or "").strip()
            if content_type:
                headers["Content-Type"] = content_type
            return BootstrapUploadTarget(
                entry_id=item["entry_id"],
                material_id=uuid.UUID(item["material_id"]),
                filename=item["filename"],
                upload_url=upload_url,
                method="PUT",
                headers=headers,
                object_key=item["object_key"],
                expires_at=expires_at,
            )

        targets = await asyncio.gather(
            *(_build_target(item) for item in pending_manifest)
        )
        return list(targets)

    def _get_storage(self) -> ObjectStorage:
        return self._storage

    @staticmethod
    def _normalize_entry_id(value: str | None, *, fallback: str) -> str:
        normalized = (value or "").strip()[:128]
        return normalized or fallback

    @staticmethod
    def _ensure_unique_entry_id(entry_id: str, used_entry_ids: set[str]) -> str:
        if entry_id not in used_entry_ids:
            used_entry_ids.add(entry_id)
            return entry_id

        suffix = 2
        while True:
            candidate = f"{entry_id}_{suffix}"
            if len(candidate) > 128:
                candidate = candidate[:128]
            if candidate not in used_entry_ids:
                used_entry_ids.add(candidate)
                return candidate
            suffix += 1

    @staticmethod
    def _normalize_title(value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        candidate = value.replace("\\", "/").split("/")[-1].strip()
        if not candidate:
            candidate = "upload.bin"
        if len(candidate) > 500:
            candidate = candidate[-500:]
        return candidate

    @staticmethod
    def _file_extension(filename: str) -> str:
        if "." not in filename:
            return ""
        return "." + filename.rsplit(".", 1)[-1].lower()

    def _validate_file_entry(
        self,
        *,
        kb: KnowledgeBase,
        extension: str,
        file_size: int,
        content_type: str | None,
    ) -> None:
        if file_size > MAX_UPLOAD_FILE_SIZE_BYTES:
            raise AppError(
                code="FILE_TOO_LARGE",
                message=f"文件大小超过限制 ({MAX_UPLOAD_FILE_SIZE_BYTES // 1024 // 1024}MB)",
                status_code=413,
            )

        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise AppError(
                code="INVALID_FILE_TYPE",
                message=f"不支持的文件类型: {extension}",
                status_code=415,
            )

        if self._is_markdown_only(kb) and extension != ".md":
            raise AppError(
                code="KB_MARKDOWN_ONLY",
                message="当前知识库仅支持上传 .md 文件",
                status_code=400,
            )

        normalized_content_type = normalize_upload_content_type(content_type)
        if (
            normalized_content_type
            and normalized_content_type not in GENERIC_UPLOAD_MIME_TYPES
            and normalized_content_type not in ALLOWED_UPLOAD_MIME_TYPES
        ):
            raise AppError(
                code="INVALID_MIME_TYPE",
                message=f"不支持的 MIME 类型: {content_type}",
                status_code=415,
            )

    @staticmethod
    def _is_markdown_only(kb: KnowledgeBase) -> bool:
        index_config = kb.index_config or {}
        if not isinstance(index_config, dict):
            return False
        chunking = index_config.get("chunking")
        if not isinstance(chunking, dict):
            return False
        strategy = str(chunking.get("general_strategy") or "").strip().lower()
        return strategy == "markdown_heading"

    @staticmethod
    def _normalize_upload_manifest(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("entry_id") or "").strip()
            material_id = str(item.get("material_id") or "").strip()
            bucket = str(item.get("bucket") or "").strip()
            object_key = str(item.get("object_key") or "").strip()
            filename = str(item.get("filename") or "").strip()
            if (
                not entry_id
                or not material_id
                or not bucket
                or not object_key
                or not filename
            ):
                continue
            normalized.append(
                {
                    "entry_id": entry_id,
                    "material_id": material_id,
                    "bucket": bucket,
                    "object_key": object_key,
                    "filename": filename,
                    "title": str(item.get("title") or "").strip() or filename,
                    "content_type": str(item.get("content_type") or "").strip() or None,
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "sha256": str(item.get("sha256") or "").strip().lower() or None,
                    "upload_status": str(item.get("upload_status") or "pending").strip()
                    or "pending",
                }
            )
        return normalized

    @staticmethod
    def _material_content_hash(manifest_item: dict[str, Any]) -> str | None:
        digest = str(manifest_item.get("sha256") or "").strip().lower()
        if digest:
            return digest[:32]
        fallback = (
            f"{manifest_item.get('bucket', '')}/{manifest_item.get('object_key', '')}"
        )
        if not fallback.strip("/"):
            return None
        return hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:32]
