"""扩展管理接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import AsyncSessionDep
from app.core.errors import not_found
from app.models.tool_extension import ExtensionStatus
from app.core.settings import get_settings
from app.schemas.extensions import (
    StdioTemplateDescriptor,
    StdioTemplateListResponse,
    ToolDescriptorListResponse,
    ToolExtensionCreate,
    ToolExtensionListResponse,
    ToolExtensionRead,
    ToolExtensionUpdate,
)
from app.schemas.pagination import PageMeta
from app.services.extension_service import ExtensionService

router = APIRouter()


@router.get("/stdio-templates", response_model=StdioTemplateListResponse)
async def list_stdio_templates() -> StdioTemplateListResponse:
    """列出可用的 STDIO 命令模板。"""
    settings = get_settings()
    items: list[StdioTemplateDescriptor] = []
    for template_id, raw in settings.mcp_stdio_templates.items():
        if not isinstance(raw, dict):
            continue
        command = str(raw.get("command", "")).strip()
        if not command:
            continue
        raw_args = raw.get("args")
        args: list[str] = []
        if isinstance(raw_args, list):
            args = [str(v) for v in raw_args]
        label = str(raw.get("label", template_id)).strip() or template_id
        description_raw = raw.get("description")
        description = (
            str(description_raw).strip()
            if isinstance(description_raw, str) and description_raw.strip()
            else None
        )
        items.append(
            StdioTemplateDescriptor(
                id=template_id,
                label=label,
                description=description,
                command=command,
                args=args,
            )
        )
    items_sorted = sorted(items, key=lambda item: item.label.lower())
    return StdioTemplateListResponse(items=items_sorted)


@router.get("", response_model=ToolExtensionListResponse)
async def list_extensions(
    db: AsyncSessionDep,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
    status_filter: ExtensionStatus | None = Query(None, description="按状态过滤"),
) -> ToolExtensionListResponse:
    """获取扩展列表。"""
    service = ExtensionService(db)
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
    db: AsyncSessionDep,
    body: ToolExtensionCreate,
) -> ToolExtensionRead:
    """创建扩展。"""
    service = ExtensionService(db)
    return await service.create_extension(body)


@router.get("/{extension_id}", response_model=ToolExtensionRead)
async def get_extension(
    db: AsyncSessionDep,
    extension_id: uuid.UUID,
) -> ToolExtensionRead:
    """获取扩展详情。"""
    service = ExtensionService(db)
    ext = await service.get_extension(extension_id)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return ext


@router.patch("/{extension_id}", response_model=ToolExtensionRead)
async def update_extension(
    db: AsyncSessionDep,
    extension_id: uuid.UUID,
    body: ToolExtensionUpdate,
) -> ToolExtensionRead:
    """更新扩展。"""
    service = ExtensionService(db)
    ext = await service.update_extension(extension_id, body)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    return ext


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(
    db: AsyncSessionDep,
    extension_id: uuid.UUID,
) -> None:
    """删除扩展。"""
    service = ExtensionService(db)
    deleted = await service.delete_extension(extension_id)
    if not deleted:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")


@router.get("/{extension_id}/tools", response_model=ToolDescriptorListResponse)
async def get_extension_tools(
    db: AsyncSessionDep,
    extension_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> ToolDescriptorListResponse:
    """获取扩展提供的工具列表。"""
    service = ExtensionService(db)
    ext = await service.get_extension(extension_id)
    if not ext:
        raise not_found("扩展不存在", code="EXTENSION_NOT_FOUND")
    items, total, connection_status, last_error, latency_ms = await service.get_tools_page(
        extension_id, skip=skip, limit=limit
    )
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
