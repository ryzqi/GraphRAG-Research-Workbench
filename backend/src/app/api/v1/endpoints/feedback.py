"""反馈 API 端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.models.feedback import FeedbackStatus
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackRead,
    FeedbackUpdate,
)
from app.schemas.pagination import PageMeta
from app.services.feedback_service import FeedbackService

router = APIRouter()


@router.post("", response_model=FeedbackRead, status_code=201)
async def create_feedback(
    req: FeedbackCreate, session: AsyncSessionDep, _user: CurrentUserDep
) -> FeedbackRead:
    """提交反馈。"""
    feedback = await FeedbackService().create(session, req)
    return FeedbackRead.model_validate(feedback)


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    session: AsyncSessionDep,
    _user: CurrentUserDep,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
    status: FeedbackStatus | None = Query(None, description="按状态过滤"),
    run_id: uuid.UUID | None = Query(None, description="按 run_id 过滤"),
) -> FeedbackListResponse:
    """列出反馈。"""
    items, total = await FeedbackService().list_page(
        session,
        status=status,
        run_id=run_id,
        skip=skip,
        limit=limit,
    )
    return FeedbackListResponse(
        items=[FeedbackRead.model_validate(f) for f in items],
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(items)) < total,
        ),
    )


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
