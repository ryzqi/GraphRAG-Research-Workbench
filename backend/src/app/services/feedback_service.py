"""反馈服务。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import Feedback, FeedbackStatus
from app.schemas.feedback import FeedbackCreate, FeedbackUpdate


class FeedbackService:
    """反馈服务。"""

    async def create(self, session: AsyncSession, req: FeedbackCreate) -> Feedback:
        """创建反馈。"""
        feedback = Feedback(
            run_id=req.run_id,
            rating=req.rating,
            comment=req.comment,
            status=FeedbackStatus.PENDING,
        )
        session.add(feedback)
        await session.commit()
        await session.refresh(feedback)
        return feedback

    async def get(self, session: AsyncSession, feedback_id: uuid.UUID) -> Feedback | None:
        """获取反馈。"""
        return await session.get(Feedback, feedback_id)

    async def list_all(
        self,
        session: AsyncSession,
        *,
        status: FeedbackStatus | None = None,
        run_id: uuid.UUID | None = None,
    ) -> list[Feedback]:
        """列出反馈（支持按状态/run_id 过滤）。"""
        stmt = select(Feedback).order_by(Feedback.created_at.desc())
        if status:
            stmt = stmt.where(Feedback.status == status)
        if run_id:
            stmt = stmt.where(Feedback.run_id == run_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self, session: AsyncSession, feedback_id: uuid.UUID, req: FeedbackUpdate
    ) -> Feedback | None:
        """更新反馈（负责人处理）。"""
        feedback = await session.get(Feedback, feedback_id)
        if feedback is None:
            return None
        if req.status is not None:
            feedback.status = req.status
        if req.resolution_note is not None:
            feedback.resolution_note = req.resolution_note
        await session.commit()
        await session.refresh(feedback)
        return feedback
