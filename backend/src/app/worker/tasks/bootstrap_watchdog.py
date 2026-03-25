"""用于处理过期 bootstrap 作业的 watchdog 任务。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.settings import get_settings
from app.models.kb_bootstrap_job import KBBootstrapJob, KBBootstrapJobStatus
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources

DEFAULT_BOOTSTRAP_WATCHDOG_BATCH_SIZE = 100
BOOTSTRAP_TIMEOUT_ERROR_CODE = "KB_BOOTSTRAP_QUEUE_TIMEOUT"
TERMINAL_MESSAGE = "任务调度超时，请检查 default/dispatch/ingestion worker 状态"


def _is_bootstrap_job_overdue(
    *,
    updated_at: datetime,
    now: datetime,
    timeout_seconds: int,
) -> bool:
    return updated_at <= now - timedelta(seconds=max(timeout_seconds, 1))


@celery_app.task(name="app.worker.tasks.bootstrap_watchdog.fail_stale_bootstrap_jobs")
def fail_stale_bootstrap_jobs(limit: int = DEFAULT_BOOTSTRAP_WATCHDOG_BATCH_SIZE) -> None:
    asyncio.run(_fail_stale_bootstrap_jobs(limit=limit))


async def _fail_stale_bootstrap_jobs(
    *,
    limit: int = DEFAULT_BOOTSTRAP_WATCHDOG_BATCH_SIZE,
) -> int:
    settings = get_settings()
    safe_limit = max(int(limit or DEFAULT_BOOTSTRAP_WATCHDOG_BATCH_SIZE), 1)
    timeout_seconds = max(int(settings.bootstrap_queued_timeout_seconds), 1)

    async with managed_task_resources(settings=settings, with_engine=True) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive guard
            return 0

        processed = 0
        async with sessionmaker() as session:
            now = datetime.now(timezone.utc)
            stale_before = now - timedelta(seconds=timeout_seconds)
            stmt = (
                select(KBBootstrapJob)
                .where(
                    KBBootstrapJob.status.in_(
                        [KBBootstrapJobStatus.QUEUED, KBBootstrapJobStatus.RUNNING]
                    ),
                    KBBootstrapJob.updated_at <= stale_before,
                )
                .order_by(KBBootstrapJob.updated_at.asc(), KBBootstrapJob.id.asc())
                .limit(safe_limit)
                .with_for_update(skip_locked=True)
            )
            rows = list((await session.execute(stmt)).scalars().all())
            if not rows:
                await session.rollback()
                return 0

            for row in rows:
                if row.status in {
                    KBBootstrapJobStatus.COMPLETED,
                    KBBootstrapJobStatus.FAILED,
                }:
                    continue
                row.status = KBBootstrapJobStatus.FAILED
                row.error_code = BOOTSTRAP_TIMEOUT_ERROR_CODE
                row.error_message = TERMINAL_MESSAGE
                row.progress_message = "任务失败：调度超时"
                row.finished_at = now
                processed += 1
            await session.commit()
        return processed

