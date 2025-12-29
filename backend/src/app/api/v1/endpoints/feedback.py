"""反馈 API 端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.models.feedback import FeedbackStatus
from app.schemas.feedback import FeedbackCreate, FeedbackRead, FeedbackUpdate
from app.services.feedback_service import FeedbackService

router = APIRouter()


@router.post("", response_model=FeedbackRead, status_code=201)
async def create_feedback(
    req: FeedbackCreate, session: AsyncSessionDep, _user: CurrentUserDep
) -> FeedbackRead:
    """提交反馈。"""
    feedback = await FeedbackService().create(session, req)
    return FeedbackRead.model_validate(feedback)


@router.get("", response_model=list[FeedbackRead])
async def list_feedback(
    session: AsyncSessionDep,
    _user: CurrentUserDep,
    status: FeedbackStatus | None = Query(None, description="按状态过滤"),
    run_id: uuid.UUID | None = Query(None, description="按 run_id 过滤"),
) -> list[FeedbackRead]:
    """列出反馈。"""
    items = await FeedbackService().list_all(session, status=status, run_id=run_id)
    return [FeedbackRead.model_validate(f) for f in items]


@router.get("/{feedback_id}", response_model=FeedbackRead)
async def get_feedback(
    feedback_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> FeedbackRead:
    """获取反馈详情。"""
    feedback = await FeedbackService().get(session, feedback_id)
    if feedback is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="反馈不存在",
            status_code=404,
        )
    return FeedbackRead.model_validate(feedback)


@router.patch("/{feedback_id}", response_model=FeedbackRead)
async def update_feedback(
    feedback_id: uuid.UUID, req: FeedbackUpdate, session: AsyncSessionDep, _user: CurrentUserDep
) -> FeedbackRead:
    """更新反馈状态与处理说明。"""
    feedback = await FeedbackService().update(session, feedback_id, req)
    if feedback is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="反馈不存在",
            status_code=404,
        )
    return FeedbackRead.model_validate(feedback)
