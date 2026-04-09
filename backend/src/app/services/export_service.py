from __future__ import annotations

import uuid

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request
from app.models.export_job import ExportJob, ExportStatus
from app.schemas.exports import ExportCreateRequest, ExportType
from app.worker.celery_app import celery_app


class ExportService:
    def __init__(self, celery: Celery | None = None) -> None:
        self._celery = celery or celery_app

    async def create_export(
        self, session: AsyncSession, req: ExportCreateRequest
    ) -> ExportJob:
        target_id: uuid.UUID | None
        if req.type == ExportType.RESEARCH:
            target_id = req.session_id
        else:
            target_id = req.run_id
        if target_id is None:
            raise bad_request(
                code="EXPORT_TARGET_MISSING",
                message="导出任务缺少目标标识",
            )

        job = ExportJob(
            status=ExportStatus.QUEUED,
            run_id=req.run_id,
            session_id=req.session_id,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        self._celery.send_task(
            "app.worker.tasks.export.run_export",
            args=[str(job.id), req.type.value, str(target_id)],
        )
        return job

    async def get_export(
        self, session: AsyncSession, export_id: uuid.UUID
    ) -> ExportJob | None:
        return await session.get(ExportJob, export_id)
