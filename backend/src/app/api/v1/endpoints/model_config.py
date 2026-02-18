"""模型配置接口。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AsyncSessionDep
from app.schemas.model_config import (
    ActiveModelUpdate,
    ModelConfigRead,
    ModelProvider,
    ProviderConfigUpdate,
)
from app.services.model_config_service import ModelConfigService

router = APIRouter()


@router.get("", response_model=ModelConfigRead)
async def get_model_config(db: AsyncSessionDep) -> ModelConfigRead:
    """获取模型配置（供应商配置 + 当前全局生效模型）。"""
    service = ModelConfigService(db)
    return await service.get_config()


@router.put("/providers/{provider}", response_model=ModelConfigRead)
async def update_model_provider(
    provider: ModelProvider,
    payload: ProviderConfigUpdate,
    db: AsyncSessionDep,
) -> ModelConfigRead:
    """更新单个供应商配置。"""
    service = ModelConfigService(db)
    return await service.update_provider(provider=provider, payload=payload)


@router.put("/active", response_model=ModelConfigRead)
async def update_active_model(
    payload: ActiveModelUpdate,
    db: AsyncSessionDep,
) -> ModelConfigRead:
    """设置全局生效模型。"""
    service = ModelConfigService(db)
    return await service.set_active_model(payload)
