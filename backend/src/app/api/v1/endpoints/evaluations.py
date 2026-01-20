"""评测 API 端点。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.sse import SSE_HEADERS, encode_sse
from app.services.streaming import stream_snapshots

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.schemas.evaluations import EvaluationRunCreateRequest, EvaluationRunRead
from app.services.evaluation_service import EvaluationService
from app.models.evaluation_run import EvaluationStatus

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


@router.get("/runs/{eval_run_id}/stream")
async def stream_evaluation_run(
    eval_run_id: uuid.UUID,
    session: AsyncSessionDep,
    request: Request,
    _user: CurrentUserDep,
):
    """流式推送评测进度。"""

    async def _fetch():
        return await EvaluationService().get_run(session, eval_run_id)

    def _serialize(run: object) -> dict:
        return EvaluationRunRead.model_validate(run).model_dump(mode="json")

    def _is_terminal(run: object) -> bool:
        status = getattr(run, "status", None)
        return status in {
            EvaluationStatus.SUCCEEDED,
            EvaluationStatus.FAILED,
            EvaluationStatus.CANCELED,
        }

    async def _events():
        yield "meta", {"eval_run_id": str(eval_run_id), "type": "evaluation"}
        async for event, data in stream_snapshots(
            _fetch,
            _serialize,
            _is_terminal,
            poll_interval=1.0,
            request=request,
        ):
            yield event, data

    return StreamingResponse(
        encode_sse(_events()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


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
