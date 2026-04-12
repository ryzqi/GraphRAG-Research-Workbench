from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_extension import ExtensionStatus, ToolExtension


class ExtensionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list(
        self,
        *,
        status: ExtensionStatus | None = None,
    ) -> list[ToolExtension]:
        stmt = select(ToolExtension).order_by(ToolExtension.created_at.desc())
        if status is not None:
            stmt = stmt.where(ToolExtension.status == status)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def list_page(
        self,
        *,
        status: ExtensionStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ToolExtension], int]:
        count_stmt = select(func.count()).select_from(ToolExtension)
        if status is not None:
            count_stmt = count_stmt.where(ToolExtension.status == status)
        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            select(ToolExtension)
            .order_by(ToolExtension.created_at.desc(), ToolExtension.id.desc())
            .offset(skip)
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(ToolExtension.status == status)
        result = await self._db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_by_id(self, extension_id: uuid.UUID) -> ToolExtension | None:
        return await self._db.get(ToolExtension, extension_id)

    def add(self, extension: ToolExtension) -> None:
        self._db.add(extension)

    async def refresh(self, extension: ToolExtension) -> None:
        await self._db.refresh(extension)

    async def delete(self, extension: ToolExtension) -> None:
        await self._db.delete(extension)
