"""Index rebuild orchestration service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.index_rebuild_job import IndexRebuildJob, IndexRebuildStatus
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase


class IndexRebuildService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, job_id: uuid.UUID) -> IndexRebuildJob | None:
        return await self._db.get(IndexRebuildJob, job_id)

    async def get_latest_by_kb(self, kb_id: uuid.UUID) -> IndexRebuildJob | None:
        stmt = (
            select(IndexRebuildJob)
            .where(IndexRebuildJob.kb_id == kb_id)
            .order_by(IndexRebuildJob.created_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalars().first()

    async def create_job(
        self,
        *,
        kb: KnowledgeBase,
        index_config: dict,
    ) -> IndexRebuildJob:
        """Replace index_config, bump config version, create snapshot, and enqueue rebuild."""

        now = datetime.now(timezone.utc)
        running_stmt = select(IndexRebuildJob).where(
            IndexRebuildJob.kb_id == kb.id,
            IndexRebuildJob.status.in_([IndexRebuildStatus.QUEUED, IndexRebuildStatus.RUNNING]),
        )
        running_result = await self._db.execute(running_stmt)
        for job in running_result.scalars().all():
            job.status = IndexRebuildStatus.CANCELED
            job.finished_at = now

        kb.index_config = index_config
        kb.current_config_version = kb.current_config_version + 1

        snapshot = KBConfigSnapshot(
            kb_id=kb.id,
            version=kb.current_config_version,
            config_json=index_config,
        )
        self._db.add(snapshot)

        job = IndexRebuildJob(kb_id=kb.id, status=IndexRebuildStatus.QUEUED)
        self._db.add(job)
        await self._db.commit()
        await self._db.refresh(job)

        from app.worker.tasks.index_rebuild import run_index_rebuild_job

        run_index_rebuild_job.delay(str(job.id))
        return job
