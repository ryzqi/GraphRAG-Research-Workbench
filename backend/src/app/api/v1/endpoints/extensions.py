"""扩展管理接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import AsyncSessionDep, CurrentUserDep, verify_admin_token
from app.core.errors import not_found
from app.models.tool_extension import ExtensionStatus
from app.schemas.extensions import (
    ToolDescriptor,
    ToolExtensionCreate,
    ToolExtensionRead,
    ToolExtensionUpdate,
)
from app.services.extension_service import ExtensionService

router = APIRouter(dependencies=[Depends(verify_admin_token)])


@router.get("", response_model=list[ToolExtensionRead])
async def list_extensions(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    status_filter: ExtensionStatus | None = None,
) -> list[ToolExtensionRead]:
    """获取扩展列表。"""
    service = ExtensionService(db, request.app.state.mcp_client)
    return await service.list_extensions(status=status_filter)


@router.post("", response_model=ToolExtensionRead, status_code=status.HTTP_201_CREATED)
async def create_extension(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    body: ToolExtensionCreate,
) -> ToolExtensionRead:
    """创建扩展。"""
    service = ExtensionService(db, request.app.state.mcp_client)
    return await service.create_extension(body)


@router.get("/{extension_id}", response_model=ToolExtensionRead)
async def get_extension(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    extension_id: uuid.UUID,
) -> ToolExtensionRead:
    """获取扩展详情。"""
    service = ExtensionService(db, request.app.state.mcp_client)
    ext = await service.get_extension(extension_id)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return ext


@router.patch("/{extension_id}", response_model=ToolExtensionRead)
async def update_extension(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    extension_id: uuid.UUID,
    body: ToolExtensionUpdate,
) -> ToolExtensionRead:
    """更新扩展。"""
    service = ExtensionService(db, request.app.state.mcp_client)
    ext = await service.update_extension(extension_id, body)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return ext


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    extension_id: uuid.UUID,
) -> None:
    """删除扩展。"""
    service = ExtensionService(db, request.app.state.mcp_client)
    deleted = await service.delete_extension(extension_id)
    if not deleted:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")


@router.get("/{extension_id}/tools", response_model=list[ToolDescriptor])
async def get_extension_tools(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    extension_id: uuid.UUID,
) -> list[ToolDescriptor]:
    """获取扩展提供的工具列表。"""
    service = ExtensionService(db, request.app.state.mcp_client)
    ext = await service.get_extension(extension_id)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return await service.get_tools(extension_id)
