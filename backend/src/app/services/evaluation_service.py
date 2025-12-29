"""评测编排服务。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_run import EvaluationRun, EvaluationStatus
from app.schemas.evaluations import EvaluationRunCreateRequest
from app.worker.celery_app import celery_app


class EvaluationService:
    """评测编排服务。"""

    def __init__(self, celery: Celery | None = None) -> None:
        self._celery = celery or celery_app

    async def create_run(
        self, session: AsyncSession, req: EvaluationRunCreateRequest
    ) -> EvaluationRun:
        """创建评测任务并入队。"""
        run = EvaluationRun(
            status=EvaluationStatus.QUEUED,
            dataset=req.dataset,
            config=req.config,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        # 入队 Celery 任务
        self._celery.send_task(
            "app.worker.tasks.evaluation.run_evaluation",
            args=[str(run.id)],
        )
        return run

    async def get_run(self, session: AsyncSession, run_id: uuid.UUID) -> EvaluationRun | None:
        """获取评测任务。"""
        return await session.get(EvaluationRun, run_id)

    async def list_runs(self, session: AsyncSession) -> list[EvaluationRun]:
        """列出所有评测任务。"""
        stmt = select(EvaluationRun).order_by(EvaluationRun.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def cancel_run(self, session: AsyncSession, run_id: uuid.UUID) -> EvaluationRun | None:
        """取消评测任务。"""
        run = await session.get(EvaluationRun, run_id)
        if run and run.status in (EvaluationStatus.QUEUED, EvaluationStatus.RUNNING):
            run.status = EvaluationStatus.CANCELED
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(run)
        return run

    async def get_results(self, session: AsyncSession, run_id: uuid.UUID) -> dict | None:
        """获取评测结果。"""
        run = await session.get(EvaluationRun, run_id)
        if run is None:
            return None
        return {
            "eval_run_id": str(run.id),
            "status": run.status.value,
            "summary": run.summary,
            "case_results": run.summary.get("case_results", []) if run.summary else [],
        }
