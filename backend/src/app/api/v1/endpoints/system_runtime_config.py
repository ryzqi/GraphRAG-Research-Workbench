from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies.services import PublicRuntimeConfigServiceDep
from app.schemas.public_runtime_config import PublicRuntimeConfigRead

router = APIRouter()


@router.get("/runtime-config", response_model=PublicRuntimeConfigRead)
async def get_public_runtime_config(
    service: PublicRuntimeConfigServiceDep,
) -> PublicRuntimeConfigRead:
    return await service.get_runtime_config()
