"""知识库服务（CRUD + 归档）。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.milvus_client import create_milvus_client
from app.integrations.object_storage import ObjectStorage
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseStatus


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: KnowledgeBaseStatus | None = None,
    ) -> tuple[list[KnowledgeBase], int]:
        """分页列出知识库。

        - status=None 表示不过滤（返回 active + archived）。
        """
        count_stmt = select(func.count()).select_from(KnowledgeBase)
        stmt = select(KnowledgeBase)
        if status is not None:
            count_stmt = count_stmt.where(KnowledgeBase.status == status)
            stmt = stmt.where(KnowledgeBase.status == status)

        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            stmt.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all()), total

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

    async def list_active_page(
        self, *, skip: int = 0, limit: int = 100
    ) -> tuple[list[KnowledgeBase], int]:
        """分页列出所有活跃知识库。"""
        return await self.list_page(
            skip=skip, limit=limit, status=KnowledgeBaseStatus.ACTIVE
        )

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
        index_config: dict | None = None,
    ) -> KnowledgeBase:
        """创建知识库。"""
        kb = KnowledgeBase(
            name=name,
            description=description,
            tags=tags,
            index_config=index_config or {},
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

    async def _cleanup_external_resources(self, kb_id: uuid.UUID) -> None:
        """清理知识库关联的外部资源（Milvus + MinIO 上传对象）。"""

        milvus_client = create_milvus_client()
        try:
            await milvus_client.delete_by_kb_id(str(kb_id))
        finally:
            await milvus_client.aclose()

        storage = ObjectStorage()
        settings = get_settings()
        await storage.remove_by_prefix(
            bucket=settings.minio_bucket_uploads,
            prefix=f"{kb_id}/",
        )

    async def delete(self, kb_id: uuid.UUID) -> bool:
        """删除知识库（级联删除关联数据）。"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            return False

        try:
            await self._db.delete(kb)
            # Flush first so DB-side failures surface before external cleanup.
            await self._db.flush()
            await self._cleanup_external_resources(kb_id)
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
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
