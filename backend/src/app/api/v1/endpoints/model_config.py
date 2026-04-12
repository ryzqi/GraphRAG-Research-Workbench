"""模型配置接口。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies.services import ModelConfigServiceDep
from app.schemas.model_config import (
    ActiveModelUpdate,
    ModelConfigRead,
    ModelProvider,
    ProviderConfigUpdate,
)

router = APIRouter()


@router.get("", response_model=ModelConfigRead)
async def get_model_config(service: ModelConfigServiceDep) -> ModelConfigRead:
    """获取模型配置（供应商配置 + 当前全局生效模型）。"""
    return await service.get_config()


@router.put("/providers/{provider}", response_model=ModelConfigRead)
async def update_model_provider(
    provider: ModelProvider,
    payload: ProviderConfigUpdate,
    service: ModelConfigServiceDep,
) -> ModelConfigRead:
    """更新单个供应商配置。"""
    return await service.update_provider(provider=provider, payload=payload)


@router.put("/active", response_model=ModelConfigRead)
async def update_active_model(
    payload: ActiveModelUpdate,
    service: ModelConfigServiceDep,
) -> ModelConfigRead:
    """设置全局生效模型。"""
    return await service.set_active_model(payload)
