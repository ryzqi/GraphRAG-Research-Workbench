"""研究 API 端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.sse import SSE_HEADERS, encode_sse
from app.models.agent_run import AgentRunStatus
from app.services.streaming import stream_snapshots

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.schemas.chats import AgentRunRead
from app.schemas.research import ResearchReportRead, ResearchRunCreateRequest
from app.services.research_service import ResearchService

router = APIRouter()


@router.post("/runs", response_model=AgentRunRead, status_code=202)
async def create_research_run(
    req: ResearchRunCreateRequest, session: AsyncSessionDep, _user: CurrentUserDep
) -> AgentRunRead:
    """发起深度研究（异步）。"""
    run = await ResearchService().create_run(session, req)
    return AgentRunRead.model_validate(run)


@router.get("/runs/{run_id}", response_model=AgentRunRead)
async def get_research_run(
    run_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> AgentRunRead:
    """查询研究状态（含阶段摘要）。"""
    run = await ResearchService().get_run(session, run_id)
    if run is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="研究任务不存在",
            status_code=404,
        )
    return AgentRunRead.model_validate(run)


@router.post("/runs/{run_id}/cancel", response_model=AgentRunRead)
async def cancel_research_run(
    run_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> AgentRunRead:
    """取消研究任务。"""
    run = await ResearchService().cancel_run(session, run_id)
    if run is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="研究任务不存在",
            status_code=404,
        )
    return AgentRunRead.model_validate(run)


@router.get("/runs/{run_id}/stream")
async def stream_research_run(
    run_id: uuid.UUID,
    session: AsyncSessionDep,
    request: Request,
    _user: CurrentUserDep,
):
    """流式推送研究进度。"""

    async def _fetch():
        return await ResearchService().get_run(session, run_id)

    def _serialize(run: object) -> dict:
        return AgentRunRead.model_validate(run).model_dump(mode="json")

    def _is_terminal(run: object) -> bool:
        status = getattr(run, "status", None)
        return status in {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELED,
        }

    async def _events():
        yield "meta", {"run_id": str(run_id), "type": "research"}
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


@router.get("/runs/{run_id}/report", response_model=ResearchReportRead)
async def get_research_report(
    run_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> ResearchReportRead:
    """获取研究报告。"""
    report = await ResearchService().get_report(session, run_id)
    if report is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="研究报告不存在",
            status_code=404,
        )
    return ResearchReportRead.model_validate(report)
