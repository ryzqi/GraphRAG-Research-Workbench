from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import TypeAdapter

from app.core.errors import AppError
from app.core.settings import get_settings
from app.models.kb_bootstrap_job import KBBootstrapJob, KBBootstrapJobStatus
from app.schemas.ingestion_batches import ManifestEntry
from app.services.ingestion_batch_service import IngestionBatchService
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources


def _normalize_entry_errors(value: Any) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    normalized: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized or None


@celery_app.task(name="app.worker.tasks.kb_bootstrap_jobs.run_kb_bootstrap_job")
def run_kb_bootstrap_job(job_id: str) -> None:
    asyncio.run(_run_kb_bootstrap_job(job_id))


async def _run_kb_bootstrap_job(job_id: str) -> None:
    settings = get_settings()
    job_uuid = uuid.UUID(job_id)

    async with managed_task_resources(settings=settings, with_engine=True) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover
            return

        async with sessionmaker() as session:
            job = await session.get(KBBootstrapJob, job_uuid)
            if job is None:
                return

            if job.status in {KBBootstrapJobStatus.COMPLETED, KBBootstrapJobStatus.FAILED}:
                return
            if job.status == KBBootstrapJobStatus.QUEUED_UPLOAD:
                return

            job.status = KBBootstrapJobStatus.RUNNING
            job.progress_message = "正在校验并提交条目"
            if job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            await session.commit()

            payload_entries = job.payload_entries or []
            try:
                entries = TypeAdapter(list[ManifestEntry]).validate_python(payload_entries)
            except Exception as exc:
                await session.rollback()
                job = await session.get(KBBootstrapJob, job_uuid)
                if job is None:
                    return
                job.status = KBBootstrapJobStatus.FAILED
                job.error_code = "KB_BOOTSTRAP_PAYLOAD_INVALID"
                job.error_message = str(exc)
                job.failed_entries = len(payload_entries)
                job.progress_message = "任务失败：提交载荷无效"
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()
                return

            try:
                service = IngestionBatchService(session)
                response = await service.submit_manifest(
                    kb_id=job.kb_id,
                    entries=entries,
                    requested_by=job.requested_by,
                )
                job.batch_id = response.batch_id
                job.status = KBBootstrapJobStatus.COMPLETED
                job.accepted_entries = response.accepted_docs
                job.failed_entries = response.failed_docs
                job.entry_errors = [err.model_dump(mode="json") for err in response.entry_errors]
                job.error_code = None
                job.error_message = None
                job.progress_message = "批次已创建，文档处理中"
            except AppError as exc:
                await session.rollback()
                job = await session.get(KBBootstrapJob, job_uuid)
                if job is None:
                    return
                details = exc.details or {}
                entry_errors = _normalize_entry_errors(details.get("entry_errors"))
                job.status = KBBootstrapJobStatus.FAILED
                job.error_code = exc.code
                job.error_message = exc.message
                job.entry_errors = entry_errors
                job.failed_entries = len(entry_errors) if entry_errors is not None else len(payload_entries)
                job.progress_message = "任务失败"
            except Exception as exc:  # pragma: no cover
                await session.rollback()
                job = await session.get(KBBootstrapJob, job_uuid)
                if job is None:
                    return
                job.status = KBBootstrapJobStatus.FAILED
                job.error_code = "KB_BOOTSTRAP_JOB_FAILED"
                job.error_message = str(exc)
                job.failed_entries = len(payload_entries)
                job.progress_message = "任务失败"

            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
