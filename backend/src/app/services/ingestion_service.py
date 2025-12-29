"""导入编排服务（创建任务→入队→查询→取消）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_job import (
    IngestionJob,
    IngestionJobItem,
    IngestionJobItemAction,
    IngestionStatus,
)
from app.schemas.ingestions import IngestionMode


class IngestionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_job(
        self,
        kb_id: uuid.UUID,
        material_ids: list[uuid.UUID],
        mode: IngestionMode = IngestionMode.CREATE,
    ) -> IngestionJob:
        """创建导入任务并入队 Celery。"""
        action = (
            IngestionJobItemAction.UPDATE
            if mode == IngestionMode.UPDATE
            else IngestionJobItemAction.CREATE
        )

        job = IngestionJob(kb_id=kb_id, status=IngestionStatus.QUEUED)
        self._db.add(job)
        await self._db.flush()

        for mid in material_ids:
            item = IngestionJobItem(job_id=job.id, material_id=mid, action=action)
            self._db.add(item)

        await self._db.commit()
        await self._db.refresh(job)

        # 入队 Celery 任务
        from app.worker.tasks.ingestion import run_ingestion_job

        run_ingestion_job.delay(str(job.id))

        return job

    async def get_by_id(self, job_id: uuid.UUID) -> IngestionJob | None:
        """根据 ID 获取导入任务。"""
        return await self._db.get(IngestionJob, job_id)

    async def list_by_kb(self, kb_id: uuid.UUID) -> list[IngestionJob]:
        """列出知识库下的所有导入任务。"""
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.kb_id == kb_id)
            .order_by(IngestionJob.created_at.desc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def cancel(self, job_id: uuid.UUID) -> IngestionJob | None:
        """取消导入任务（仅 queued/running 状态可取消）。"""
        job = await self.get_by_id(job_id)
        if not job:
            return None

        if job.status not in (IngestionStatus.QUEUED, IngestionStatus.RUNNING):
            return job

        job.status = IngestionStatus.CANCELED
        job.finished_at = datetime.now(timezone.utc)
        await self._db.commit()
        await self._db.refresh(job)
        return job

    async def update_status(
        self,
        job_id: uuid.UUID,
        status: IngestionStatus,
        *,
        error_message: str | None = None,
        stats: dict | None = None,
    ) -> IngestionJob | None:
        """更新导入任务状态（供 Celery 任务调用）。"""
        job = await self.get_by_id(job_id)
        if not job:
            return None

        job.status = status
        now = datetime.now(timezone.utc)

        if status == IngestionStatus.RUNNING and job.started_at is None:
            job.started_at = now

        if status in (
            IngestionStatus.SUCCEEDED,
            IngestionStatus.FAILED,
            IngestionStatus.CANCELED,
        ):
            job.finished_at = now

        if error_message is not None:
            job.error_message = error_message

        if stats is not None:
            job.stats = stats

        await self._db.commit()
        await self._db.refresh(job)
        return job
