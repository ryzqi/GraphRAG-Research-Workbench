"""扩展管理服务。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.mcp_client import MCPClient, ToolDefinition
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.schemas.extensions import (
    ToolDescriptor,
    ToolExtensionCreate,
    ToolExtensionRead,
    ToolExtensionUpdate,
)


class ExtensionService:
    def __init__(self, db: AsyncSession, mcp: MCPClient) -> None:
        self._db = db
        self._mcp = mcp

    async def list_extensions(
        self, *, status: ExtensionStatus | None = None
    ) -> list[ToolExtensionRead]:
        """获取扩展列表。"""
        stmt = select(ToolExtension).order_by(ToolExtension.created_at.desc())
        if status:
            stmt = stmt.where(ToolExtension.status == status)

        result = await self._db.execute(stmt)
        extensions = result.scalars().all()
        return [ToolExtensionRead.model_validate(e) for e in extensions]

    async def list_extensions_page(
        self,
        *,
        status: ExtensionStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ToolExtensionRead], int]:
        """分页获取扩展列表。"""
        count_stmt = select(func.count()).select_from(ToolExtension)
        if status:
            count_stmt = count_stmt.where(ToolExtension.status == status)
        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            select(ToolExtension)
            .order_by(ToolExtension.created_at.desc(), ToolExtension.id.desc())
            .offset(skip)
            .limit(limit)
        )
        if status:
            stmt = stmt.where(ToolExtension.status == status)

        result = await self._db.execute(stmt)
        extensions = result.scalars().all()
        return [ToolExtensionRead.model_validate(e) for e in extensions], total

    async def get_extension(self, extension_id: uuid.UUID) -> ToolExtensionRead | None:
        """获取单个扩展。"""
        ext = await self._db.get(ToolExtension, extension_id)
        return ToolExtensionRead.model_validate(ext) if ext else None

    async def create_extension(self, data: ToolExtensionCreate) -> ToolExtensionRead:
        """创建扩展。"""
        ext = ToolExtension(
            name=data.name,
            transport=data.transport,
            endpoint=data.endpoint,
            scope=data.scope,
        )
        self._db.add(ext)
        await self._db.commit()
        await self._db.refresh(ext)
        return ToolExtensionRead.model_validate(ext)

    async def update_extension(
        self, extension_id: uuid.UUID, data: ToolExtensionUpdate
    ) -> ToolExtensionRead | None:
        """更新扩展。"""
        ext = await self._db.get(ToolExtension, extension_id)
        if not ext:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(ext, key, value)

        await self._db.commit()
        await self._db.refresh(ext)
        return ToolExtensionRead.model_validate(ext)

    async def delete_extension(self, extension_id: uuid.UUID) -> bool:
        """删除扩展。"""
        ext = await self._db.get(ToolExtension, extension_id)
        if not ext:
            return False

        await self._mcp.disconnect(str(extension_id))
        await self._db.delete(ext)
        await self._db.commit()
        return True

    async def get_tools(self, extension_id: uuid.UUID) -> list[ToolDescriptor]:
        """获取扩展提供的工具列表。"""
        ext = await self._db.get(ToolExtension, extension_id)
        if not ext or ext.status != ExtensionStatus.ENABLED:
            return []

        tools = await self._mcp.connect(
            str(extension_id), ext.transport.value, ext.endpoint, ext.scope
        )
        return [
            ToolDescriptor(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in tools
        ]

    async def get_tools_page(
        self,
        extension_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ToolDescriptor], int]:
        """分页获取扩展提供的工具列表。"""
        tools = await self.get_tools(extension_id)
        tools_sorted = sorted(tools, key=lambda t: t.name)
        total = len(tools_sorted)
        return tools_sorted[skip : skip + limit], total

    async def get_all_enabled_tools(self) -> dict[uuid.UUID, list[ToolDefinition]]:
        """获取所有启用扩展的工具。"""
        stmt = select(ToolExtension).where(
            ToolExtension.status == ExtensionStatus.ENABLED
        )
        result = await self._db.execute(stmt)
        extensions = result.scalars().all()

        tools_map: dict[uuid.UUID, list[ToolDefinition]] = {}
        for ext in extensions:
            tools = await self._mcp.connect(
                str(ext.id), ext.transport.value, ext.endpoint, ext.scope
            )
            if tools:
                tools_map[ext.id] = tools

        return tools_map
