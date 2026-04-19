"""知识库服务（CRUD + 归档）。"""

from __future__ import annotations

from collections.abc import Collection
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.milvus_client import create_milvus_client
from app.integrations.object_storage import ObjectStorage
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseReadiness,
    KnowledgeBaseStatus,
)


async def touch_kb_updated_at(db: AsyncSession, kb_id: uuid.UUID) -> None:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        return
    kb.updated_at = datetime.now(timezone.utc)
    await db.flush()


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession, *, object_storage: ObjectStorage) -> None:
        self._db = db
        self._storage = object_storage

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: KnowledgeBaseStatus | None = None,
        readiness: KnowledgeBaseReadiness | None = None,
    ) -> tuple[list[KnowledgeBase], int]:
        """分页列出知识库。"""

        count_stmt = select(func.count()).select_from(KnowledgeBase)
        stmt = select(KnowledgeBase)

        if status is not None:
            count_stmt = count_stmt.where(KnowledgeBase.status == status)
            stmt = stmt.where(KnowledgeBase.status == status)
        if readiness is not None:
            count_stmt = count_stmt.where(KnowledgeBase.readiness == readiness)
            stmt = stmt.where(KnowledgeBase.readiness == readiness)

        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            stmt.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all()), total

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[KnowledgeBase]:
        stmt = (
            select(KnowledgeBase)
            .where(KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE)
            .order_by(KnowledgeBase.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def list_selectable_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[KnowledgeBase], int]:
        return await self.list_page(
            skip=skip,
            limit=limit,
            status=KnowledgeBaseStatus.ACTIVE,
            readiness=KnowledgeBaseReadiness.READY,
        )

    async def list_active_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[KnowledgeBase], int]:
        return await self.list_page(
            skip=skip, limit=limit, status=KnowledgeBaseStatus.ACTIVE
        )

    async def get_by_id(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        return await self._db.get(KnowledgeBase, kb_id)

    async def get_by_ids(self, kb_ids: list[uuid.UUID]) -> list[KnowledgeBase]:
        if not kb_ids:
            return []
        stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(KnowledgeBase.name == name)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        description: str | None = None,
        tags: list[str] | None = None,
        index_config: dict | None = None,
        commit: bool = True,
    ) -> KnowledgeBase:
        """创建知识库并初始化 version=1 快照。"""

        now = datetime.now(timezone.utc)
        kb = KnowledgeBase(
            name=name,
            description=description,
            tags=tags,
            index_config=index_config or {},
            status=KnowledgeBaseStatus.ACTIVE,
            readiness=KnowledgeBaseReadiness.NOT_READY,
            readiness_updated_at=now,
            current_config_version=1,
        )
        self._db.add(kb)
        await self._db.flush()

        snapshot = KBConfigSnapshot(
            kb_id=kb.id,
            version=1,
            config_json=kb.index_config or {},
            is_active=True,
        )
        self._db.add(snapshot)

        if commit:
            await self._db.commit()
            await self._db.refresh(kb)
        return kb

    async def update(
        self,
        *,
        kb_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        fields_to_update: Collection[str] | None = None,
    ) -> KnowledgeBase | None:
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None

        submitted_fields = (
            set(fields_to_update)
            if fields_to_update is not None
            else {
                field_name
                for field_name, value in (
                    ("name", name),
                    ("description", description),
                    ("tags", tags),
                )
                if value is not None
            }
        )

        if "name" in submitted_fields:
            kb.name = name
        if "description" in submitted_fields:
            kb.description = description
        if "tags" in submitted_fields:
            kb.tags = tags

        await self._db.commit()
        await self._db.refresh(kb)
        return kb

    async def _cleanup_external_resources(self, kb_id: uuid.UUID) -> None:
        milvus_client = create_milvus_client()
        try:
            await milvus_client.delete_by_kb_id(str(kb_id))
        finally:
            await milvus_client.aclose()

        settings = get_settings()
        await self._storage.remove_by_prefix(
            bucket=settings.minio_bucket_uploads,
            prefix=f"{kb_id}/",
        )

    async def delete(self, kb_id: uuid.UUID) -> bool:
        kb = await self.get_by_id(kb_id)
        if not kb:
            return False

        try:
            await self._db.delete(kb)
            await self._db.flush()
            await self._cleanup_external_resources(kb_id)
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
        return True

    async def archive(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None

        kb.status = KnowledgeBaseStatus.ARCHIVED
        await touch_kb_updated_at(self._db, kb_id)
        await self._db.commit()
        await self._db.refresh(kb)
        return kb
