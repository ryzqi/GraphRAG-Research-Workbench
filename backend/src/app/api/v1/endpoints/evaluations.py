"""评测 API 端点。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.schemas.evaluations import EvaluationRunCreateRequest, EvaluationRunRead
from app.services.evaluation_service import EvaluationService

router = APIRouter()


@router.post("/runs", response_model=EvaluationRunRead, status_code=202)
async def create_evaluation_run(
    req: EvaluationRunCreateRequest, session: AsyncSessionDep, _user: CurrentUserDep
) -> EvaluationRunRead:
    """发起对比评测（异步）。"""
    run = await EvaluationService().create_run(session, req)
    return EvaluationRunRead.model_validate(run)


@router.get("/runs/{eval_run_id}", response_model=EvaluationRunRead)
async def get_evaluation_run(
    eval_run_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> EvaluationRunRead:
    """查询评测状态。"""
    run = await EvaluationService().get_run(session, eval_run_id)
    if run is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="评测任务不存在",
            status_code=404,
        )
    return EvaluationRunRead.model_validate(run)


@router.get("/runs/{eval_run_id}/results")
async def get_evaluation_results(
    eval_run_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> dict[str, Any]:
    """获取评测结果（对比汇总 + 题目级明细）。"""
    results = await EvaluationService().get_results(session, eval_run_id)
    if results is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="评测任务不存在",
            status_code=404,
        )
    return results


@router.post("/runs/{eval_run_id}/cancel", response_model=EvaluationRunRead)
async def cancel_evaluation_run(
    eval_run_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> EvaluationRunRead:
    """取消评测任务。"""
    run = await EvaluationService().cancel_run(session, eval_run_id)
    if run is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="评测任务不存在",
            status_code=404,
        )
    return EvaluationRunRead.model_validate(run)
