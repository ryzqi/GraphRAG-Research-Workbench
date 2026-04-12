from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies.services import QueueHealthServiceDep
from app.schemas.system import QueueHealthRead

router = APIRouter()


@router.get("/system/queue-health", response_model=QueueHealthRead)
async def get_queue_health(
    service: QueueHealthServiceDep,
) -> QueueHealthRead:
    return await service.get_queue_health()
