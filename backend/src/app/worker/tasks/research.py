"""Research worker tasks。"""

from __future__ import annotations

import asyncio
import uuid

from app.core.settings import get_settings
from app.models.research_session import ResearchSessionStatus
from app.services.deep_research_runtime import build_deep_research_runtime_runner
from app.services.research_service import build_research_service
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources


@celery_app.task(name="app.worker.tasks.research.run_research_session")
def run_research_session(session_id: str) -> None:
    asyncio.run(_run_research_session(session_id))


async def _run_research_session(session_id: str) -> None:
    settings = get_settings()
    session_uuid = uuid.UUID(session_id)
    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_http=True,
        with_redis=True,
        with_milvus=True,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover
            return

        async with sessionmaker() as db:
            runtime_runner = await build_deep_research_runtime_runner(
                settings=settings,
                db=db,
                http_client=resources.http_client,
                redis=resources.redis,
                milvus=resources.milvus,
                embedding=resources.embedding_client,
            )
            service = build_research_service(db=db, runtime_runner=runtime_runner)
            session = await service.get_session(session_uuid)
            if session.status not in {
                ResearchSessionStatus.QUEUED,
                ResearchSessionStatus.RESUMING,
            }:
                return

            try:
                await service.execute_session(
                    session=session,
                    plan_snapshot=service.read_plan_snapshot(session),
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                session = await service.get_session(session_uuid)
                if session.status.is_terminal():
                    return
                await service.fail_session(
                    session=session,
                    exc=exc,
                    phase=session.runtime_phase or "runtime",
                )
                await db.commit()
