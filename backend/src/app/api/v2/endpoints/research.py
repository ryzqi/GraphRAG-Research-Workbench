"""Research v2 API endpoints。"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import AsyncSessionDep
from app.api.sse import SSE_HEADERS, encode_sse
from app.models.research_session import TERMINAL_RESEARCH_SESSION_STATUSES
from app.schemas.research_v2 import (
    ResearchArtifactsRead,
    ResearchInterruptRequest,
    ResearchResumeRequest,
    ResearchSessionCreateRequest,
    ResearchSessionRead,
)
from app.services.research_v2_service import ResearchV2Service

router = APIRouter()


@router.post("/sessions", response_model=ResearchSessionRead, status_code=202)
async def create_research_session(
    req: ResearchSessionCreateRequest, session: AsyncSessionDep
) -> ResearchSessionRead:
    research_session = await ResearchV2Service().create_session(session, req)
    return ResearchSessionRead.model_validate(research_session)


@router.get("/sessions/{session_id}", response_model=ResearchSessionRead)
async def get_research_session(
    session_id: uuid.UUID,
    session: AsyncSessionDep,
) -> ResearchSessionRead:
    research_session = await ResearchV2Service().get_session(session, session_id)
    if research_session is None:
        from app.core.errors import not_found

        raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")
    return ResearchSessionRead.model_validate(research_session)


@router.get("/sessions/{session_id}/stream")
async def stream_research_session(
    session_id: uuid.UUID,
    session: AsyncSessionDep,
    request: Request,
    resume_from_event_id: str | None = None,
):
    service = ResearchV2Service()
    last_event_id = request.headers.get("Last-Event-ID")

    async def _events():
        yield "meta", {
            "session_id": str(session_id),
            "last_event_id": last_event_id,
            "resume_from_event_id": resume_from_event_id,
        }

        cursor = last_event_id or resume_from_event_id
        while True:
            events = await service.get_events_since(
                session,
                session_id=session_id,
                last_event_id=cursor if last_event_id else None,
                resume_from_event_id=None if last_event_id else cursor,
            )
            for envelope in events:
                cursor = envelope.event_id
                yield "event", envelope.model_dump(mode="json")

            current = await service.get_session(session, session_id)
            if current is None:
                yield "error", {
                    "code": "RESEARCH_SESSION_NOT_FOUND",
                    "message": "研究会话不存在",
                }
                return
            if current.status in TERMINAL_RESEARCH_SESSION_STATUSES:
                yield "final", ResearchSessionRead.model_validate(current).model_dump(mode="json")
                return

            if await request.is_disconnected():
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(
        encode_sse(_events()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/sessions/{session_id}/interrupt", response_model=ResearchSessionRead)
async def interrupt_research_session(
    session_id: uuid.UUID,
    req: ResearchInterruptRequest,
    session: AsyncSessionDep,
) -> ResearchSessionRead:
    research_session = await ResearchV2Service().interrupt_session(
        session,
        session_id=session_id,
        reason=req.reason,
    )
    return ResearchSessionRead.model_validate(research_session)


@router.post("/sessions/{session_id}/resume", response_model=ResearchSessionRead)
async def resume_research_session(
    session_id: uuid.UUID,
    req: ResearchResumeRequest,
    session: AsyncSessionDep,
) -> ResearchSessionRead:
    research_session = await ResearchV2Service().resume_session(
        session,
        session_id=session_id,
        req=req,
    )
    return ResearchSessionRead.model_validate(research_session)


@router.get("/sessions/{session_id}/artifacts", response_model=ResearchArtifactsRead)
async def get_research_artifacts(
    session_id: uuid.UUID,
    session: AsyncSessionDep,
) -> ResearchArtifactsRead:
    return await ResearchV2Service().get_artifacts(session, session_id=session_id)

