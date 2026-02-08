"""研究编排服务。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select

from app.core.errors import bad_request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseReadiness, KnowledgeBaseStatus
from app.models.research_report import ResearchReport
from app.schemas.research import ResearchRunCreateRequest
from app.worker.celery_app import celery_app


class ResearchService:
    """研究编排服务。"""

    def __init__(self, celery: Celery | None = None) -> None:
        self._celery = celery or celery_app

    async def create_run(
        self, session: AsyncSession, req: ResearchRunCreateRequest
    ) -> AgentRun:
        """创建研究任务并入队。"""
        if req.selected_kb_ids:
            stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(req.selected_kb_ids))
            kbs = list((await session.execute(stmt)).scalars().all())
            if len(kbs) != len(req.selected_kb_ids):
                raise bad_request(code="KB_NOT_FOUND", message="存在不存在的知识库")

            not_selectable = [
                str(kb.id)
                for kb in kbs
                if kb.status != KnowledgeBaseStatus.ACTIVE
                or kb.readiness != KnowledgeBaseReadiness.READY
            ]
            if not_selectable:
                raise bad_request(
                    code="KB_NOT_SELECTABLE",
                    message="所选知识库尚不可用于业务入口",
                    details={"kb_ids": not_selectable},
                )

        run = AgentRun(
            run_type=AgentRunType.RESEARCH,
            question=req.question,
            selected_kb_ids=req.selected_kb_ids,
            allow_external=req.allow_external,
            mode=req.mode,
            status=AgentRunStatus.RUNNING,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        # 入队 Celery 任务
        self._celery.send_task(
            "app.worker.tasks.research.run_research",
            args=[
                str(run.id),
                req.question,
                [str(kb_id) for kb_id in req.selected_kb_ids],
                req.allow_external,
                req.mode.value,
            ],
        )
        return run

    async def get_run(self, session: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
        """获取研究任务。"""
        return await session.get(AgentRun, run_id)

    async def cancel_run(self, session: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
        """取消研究任务。"""
        run = await session.get(AgentRun, run_id)
        if run and run.status == AgentRunStatus.RUNNING:
            run.status = AgentRunStatus.CANCELED
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(run)
        return run

    async def get_report(
        self, session: AsyncSession, run_id: uuid.UUID
    ) -> ResearchReport | None:
        """获取研究报告。"""
        stmt = select(ResearchReport).where(ResearchReport.run_id == run_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
