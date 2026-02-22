from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import AsyncSessionDep
from app.schemas.system import QueueHealthRead
from app.services.queue_health_service import QueueHealthService

router = APIRouter()


@router.get("/system/queue-health", response_model=QueueHealthRead)
async def get_queue_health(
    request: Request,
    session: AsyncSessionDep,
) -> QueueHealthRead:
    service = QueueHealthService(
        session,
        redis=request.app.state.redis,
    )
    return await service.get_queue_health()

