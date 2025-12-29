"""知识库服务（CRUD + 归档）。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseStatus


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[KnowledgeBase]:
        """列出所有活跃知识库。"""
        stmt = (
            select(KnowledgeBase)
            .where(KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE)
            .order_by(KnowledgeBase.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        """根据 ID 获取知识库。"""
        return await self._db.get(KnowledgeBase, kb_id)

    async def get_by_ids(self, kb_ids: list[uuid.UUID]) -> list[KnowledgeBase]:
        """根据 ID 列表获取知识库。"""
        if not kb_ids:
            return []
        stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> KnowledgeBase | None:
        """根据名称获取知识库。"""
        stmt = select(KnowledgeBase).where(KnowledgeBase.name == name)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        name: str,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> KnowledgeBase:
        """创建知识库。"""
        kb = KnowledgeBase(
            name=name,
            description=description,
            tags=tags,
            status=KnowledgeBaseStatus.ACTIVE,
        )
        self._db.add(kb)
        await self._db.commit()
        await self._db.refresh(kb)
        return kb

    async def update(
        self,
        kb_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> KnowledgeBase | None:
        """更新知识库。"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None

        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        if tags is not None:
            kb.tags = tags

        await self._db.commit()
        await self._db.refresh(kb)
        return kb

    async def delete(self, kb_id: uuid.UUID) -> bool:
        """删除知识库（级联删除关联数据）。"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            return False

        await self._db.delete(kb)
        await self._db.commit()
        return True

    async def archive(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        """归档知识库。"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None

        kb.status = KnowledgeBaseStatus.ARCHIVED
        await self._db.commit()
        await self._db.refresh(kb)
        return kb
