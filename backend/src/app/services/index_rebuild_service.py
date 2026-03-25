"""索引重建编排服务。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.index_rebuild_job import IndexRebuildJob, IndexRebuildStatus
from app.models.index_rebuild_task_outbox import (
    IndexRebuildTaskOutbox,
    IndexRebuildTaskOutboxStatus,
)
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)
INDEX_REBUILD_TASK_NAME = "app.worker.tasks.index_rebuild.run_index_rebuild_job"


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
        """替换索引配置快照并将重建任务入队。"""

        now = datetime.now(timezone.utc)
        running_stmt = select(IndexRebuildJob).where(
            IndexRebuildJob.kb_id == kb.id,
            IndexRebuildJob.status.in_([IndexRebuildStatus.QUEUED, IndexRebuildStatus.RUNNING]),
        )
        running_result = await self._db.execute(running_stmt)
        for job in running_result.scalars().all():
            job.status = IndexRebuildStatus.CANCELED
            job.finished_at = now

        max_version_stmt = select(func.max(KBConfigSnapshot.version)).where(
            KBConfigSnapshot.kb_id == kb.id
        )
        max_version = (await self._db.execute(max_version_stmt)).scalar_one()
        next_version = int(max_version or 0) + 1

        deactivate_stmt = select(KBConfigSnapshot).where(
            KBConfigSnapshot.kb_id == kb.id,
            KBConfigSnapshot.is_active.is_(True),
        )
        active_result = await self._db.execute(deactivate_stmt)
        for snapshot in active_result.scalars().all():
            snapshot.is_active = False

        kb.index_config = index_config
        kb.current_config_version = next_version

        snapshot = KBConfigSnapshot(
            kb_id=kb.id,
            version=next_version,
            config_json=index_config,
            is_active=True,
        )
        self._db.add(snapshot)

        job = IndexRebuildJob(
            id=uuid.uuid4(),
            kb_id=kb.id,
            status=IndexRebuildStatus.QUEUED,
        )
        self._db.add(job)
        self._db.add(
            IndexRebuildTaskOutbox(
                job_id=job.id,
                task_name=INDEX_REBUILD_TASK_NAME,
                payload={"job_id": str(job.id)},
                status=IndexRebuildTaskOutboxStatus.PENDING,
                attempts=0,
                max_attempts=20,
                next_retry_at=None,
                dispatched_at=None,
                last_error=None,
            )
        )
        await self._db.commit()
        await self._db.refresh(job)

        self._trigger_outbox_dispatch()
        return job

    def _trigger_outbox_dispatch(self) -> None:
        try:
            from app.worker.tasks.index_rebuild_outbox_dispatcher import (
                dispatch_index_rebuild_outbox,
            )

            dispatch_index_rebuild_outbox.delay()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Failed to trigger index rebuild outbox dispatcher",
                extra={"error": str(exc)},
            )
