"""Research worker tasks。"""

from __future__ import annotations

import uuid

from app.core.settings import get_settings
from app.models.research_session import ResearchSessionStatus
from app.services.research_service import build_research_service
from app.worker.async_runtime import run_in_worker_async_runtime
from app.worker.celery_app import celery_app
from app.worker.deep_research_runtime_cache import get_cached_runner
from app.worker.task_resources import managed_task_resources


@celery_app.task(name="app.worker.tasks.research.run_research_session")
def run_research_session(session_id: str) -> None:
    run_in_worker_async_runtime(_run_research_session(session_id))


async def _run_research_session(session_id: str) -> None:
    settings = get_settings()
    session_uuid = uuid.UUID(session_id)
    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_milvus=False,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover
            return

        runtime_runner = await get_cached_runner(settings=settings)
        async with sessionmaker() as bootstrap_db:
            service = build_research_service(
                db=bootstrap_db,
                sessionmaker=sessionmaker,
                runtime_runner=runtime_runner,
            )
            session = await service.get_session(session_uuid)
            if session.status != ResearchSessionStatus.QUEUED:
                return
            plan_snapshot = service.read_plan_snapshot(session)

        try:
            async with sessionmaker() as run_db:
                run_service = build_research_service(
                    db=run_db,
                    sessionmaker=sessionmaker,
                    runtime_runner=runtime_runner,
                )
                run_session = await run_service.get_session(session_uuid)
                if run_session.status != ResearchSessionStatus.QUEUED:
                    return
                await run_service.execute_session(
                    session=run_session,
                    plan_snapshot=plan_snapshot,
                )
        except Exception as exc:
            async with sessionmaker() as fail_db:
                fail_service = build_research_service(
                    db=fail_db,
                    sessionmaker=sessionmaker,
                    runtime_runner=runtime_runner,
                )
                session = await fail_service.get_session(session_uuid)
                if session.status.is_terminal():
                    return
                await fail_service.fail_session(
                    session=session,
                    exc=exc,
                    phase=session.runtime_phase or "runtime",
                )
