"""扩展管理接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.dependencies.services import ExtensionServiceDep
from app.core.errors import not_found
from app.models.tool_extension import ExtensionStatus
from app.schemas.extensions import (
    ToolDescriptorListResponse,
    ToolExtensionCreate,
    ToolExtensionListResponse,
    ToolExtensionRead,
    ToolExtensionUpdate,
)
from app.schemas.pagination import PageMeta

router = APIRouter()


@router.get("", response_model=ToolExtensionListResponse)
async def list_extensions(
    service: ExtensionServiceDep,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
    status_filter: ExtensionStatus | None = Query(None, description="按状态过滤"),
) -> ToolExtensionListResponse:
    """获取扩展列表。"""
    items, total = await service.list_extensions_page(
        status=status_filter, skip=skip, limit=limit
    )
    return ToolExtensionListResponse(
        items=items,
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(items)) < total,
        ),
    )


@router.post("", response_model=ToolExtensionRead, status_code=status.HTTP_201_CREATED)
async def create_extension(
    service: ExtensionServiceDep,
    body: ToolExtensionCreate,
) -> ToolExtensionRead:
    """创建扩展。"""
    return await service.create_extension(body)


@router.get("/{extension_id}", response_model=ToolExtensionRead)
async def get_extension(
    service: ExtensionServiceDep,
    extension_id: uuid.UUID,
) -> ToolExtensionRead:
    """获取扩展详情。"""
    ext = await service.get_extension(extension_id)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return ext


@router.patch("/{extension_id}", response_model=ToolExtensionRead)
async def update_extension(
    service: ExtensionServiceDep,
    extension_id: uuid.UUID,
    body: ToolExtensionUpdate,
) -> ToolExtensionRead:
    """更新扩展。"""
    ext = await service.update_extension(extension_id, body)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return ext


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(
    service: ExtensionServiceDep,
    extension_id: uuid.UUID,
) -> None:
    """删除扩展。"""
    deleted = await service.delete_extension(extension_id)
    if not deleted:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")


@router.get("/{extension_id}/tools", response_model=ToolDescriptorListResponse)
async def get_extension_tools(
    service: ExtensionServiceDep,
    extension_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> ToolDescriptorListResponse:
    """获取扩展提供的工具列表。"""
    ext = await service.get_extension(extension_id)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    (
        items,
        total,
        connection_status,
        last_error,
        latency_ms,
    ) = await service.get_tools_page(extension_id, skip=skip, limit=limit)
    return ToolDescriptorListResponse(
        items=items,
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(items)) < total,
        ),
        connection_status=connection_status,
        last_error=last_error,
        latency_ms=latency_ms,
    )
