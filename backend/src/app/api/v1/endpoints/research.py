"""当前 research 会话端点。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Protocol, cast

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AsyncSessionDep
from app.api.sse import SSE_HEADERS, encode_sse
from app.schemas.research import (
    ResearchArtifactsResponse,
    ResearchClarificationSubmitRequest,
    ResearchPlanUpdateRequest,
    ResearchSessionAccepted,
    ResearchSessionCreateRequest,
    ResearchStopRequest,
    ResearchStreamResumeParams,
)
from app.services.research_service import ResearchService, build_research_service

router = APIRouter()


class _ResearchServiceFactory(Protocol):
    def __call__(self, *, db: AsyncSession, request: Request) -> ResearchService: ...


def _get_research_service(*, request: Request, db: AsyncSession) -> ResearchService:
    raw_factory = getattr(request.app.state, "research_service_factory", None)
    if callable(raw_factory):
        factory = cast(_ResearchServiceFactory, raw_factory)
        return factory(db=db, request=request)
    return build_research_service(db=db)


async def _emit_research_events(
    *,
    service: ResearchService,
    session,
    after_event_id: str | None,
) -> AsyncIterator[tuple[str, object]]:
    for envelope in service.list_event_envelopes(session, after_event_id=after_event_id):
        yield "research.event", envelope.model_dump(mode="json")


@router.post(
    "/sessions",
    response_model=ResearchSessionAccepted,
    status_code=status.HTTP_201_CREATED,
)
async def create_research_session(
    db: AsyncSessionDep,
    request: Request,
    body: ResearchSessionCreateRequest,
) -> ResearchSessionAccepted:
    service = _get_research_service(request=request, db=db)
    session_id = uuid.uuid4()
    session, plan_result = await service.create_session(
        body,
        session_id=session_id,
        thread_id=str(session_id),
    )
    await db.commit()
    return ResearchSessionAccepted(
        session_id=session.id,
        status=session.status,
        plan_snapshot=plan_result.plan_snapshot,
        clarification_request=plan_result.clarification_request,
    )


@router.post(
    "/sessions/{session_id}/clarification",
    response_model=ResearchSessionAccepted,
)
async def submit_research_clarification(
    session_id: uuid.UUID,
    db: AsyncSessionDep,
    request: Request,
    body: ResearchClarificationSubmitRequest,
) -> ResearchSessionAccepted:
    service = _get_research_service(request=request, db=db)
    session = await service.get_session(session_id)
    session, plan_result = await service.submit_clarification(
        session=session,
        answer=body.answer,
    )
    await db.commit()
    return ResearchSessionAccepted(
        session_id=session.id,
        status=session.status,
        plan_snapshot=plan_result.plan_snapshot,
        clarification_request=plan_result.clarification_request,
    )


@router.post(
    "/sessions/{session_id}/plan",
    response_model=ResearchSessionAccepted,
)
async def update_research_plan(
    session_id: uuid.UUID,
    db: AsyncSessionDep,
    request: Request,
    body: ResearchPlanUpdateRequest,
) -> ResearchSessionAccepted:
    service = _get_research_service(request=request, db=db)
    session = await service.get_session(session_id)
    session, plan_result = await service.update_plan(session=session, feedback=body.feedback)
    await db.commit()
    return ResearchSessionAccepted(
        session_id=session.id,
        status=session.status,
        plan_snapshot=plan_result.plan_snapshot,
        clarification_request=plan_result.clarification_request,
    )


@router.post(
    "/sessions/{session_id}/start",
    response_model=ResearchSessionAccepted,
)
async def start_research_session(
    session_id: uuid.UUID,
    db: AsyncSessionDep,
    request: Request,
) -> ResearchSessionAccepted:
    service = _get_research_service(request=request, db=db)
    session = await service.get_session(session_id)
    session = await service.start_session(session=session)
    await db.commit()
    return ResearchSessionAccepted(
        session_id=session.id,
        status=session.status,
        plan_snapshot=service.read_plan_snapshot(session),
        clarification_request=None,
    )


@router.get("/sessions/{session_id}/stream")
async def stream_research_session(
    session_id: uuid.UUID,
    db: AsyncSessionDep,
    request: Request,
    resume_from_event_id: str | None = None,
) -> StreamingResponse:
    service = _get_research_service(request=request, db=db)
    session = await service.get_session(session_id)
    resume_params = ResearchStreamResumeParams(resume_from_event_id=resume_from_event_id)
    after_event_id = resume_params.effective_after_event_id(
        last_event_id=request.headers.get("Last-Event-ID")
    )
    stream = encode_sse(
        _emit_research_events(
            service=service,
            session=session,
            after_event_id=after_event_id,
        )
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post(
    "/sessions/{session_id}/stop",
    response_model=ResearchSessionAccepted,
)
async def stop_research_session(
    session_id: uuid.UUID,
    db: AsyncSessionDep,
    request: Request,
    body: ResearchStopRequest,
) -> ResearchSessionAccepted:
    service = _get_research_service(request=request, db=db)
    session = await service.get_session(session_id)
    session = await service.stop_session(session=session, reason=body.reason)
    await db.commit()
    return ResearchSessionAccepted(session_id=session.id, status=session.status)


@router.get(
    "/sessions/{session_id}/artifacts",
    response_model=ResearchArtifactsResponse,
)
async def list_research_artifacts(
    session_id: uuid.UUID,
    db: AsyncSessionDep,
    request: Request,
) -> ResearchArtifactsResponse:
    service = _get_research_service(request=request, db=db)
    session = await service.get_session(session_id)
    return service.build_artifacts_response(session)
