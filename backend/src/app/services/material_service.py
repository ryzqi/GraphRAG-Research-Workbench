"""资料服务（创建/列表/上传）。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import BinaryIO

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.core.validators import validate_file_upload
from app.integrations.object_storage import ObjectRef, ObjectStorage
from app.models.document_chunk import DocumentChunk
from app.models.source_material import SourceMaterial, SourceType
from app.services.url_ingestion_guard import build_url_ingestion_guard


class MaterialService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._storage = ObjectStorage()
        self._settings = get_settings()
        self._url_guard = build_url_ingestion_guard(self._settings)

    async def list_by_kb(
        self, kb_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[SourceMaterial]:
        """列出知识库下的所有资料。"""
        stmt = (
            select(SourceMaterial)
            .where(SourceMaterial.kb_id == kb_id)
            .order_by(SourceMaterial.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_kb_page(
        self, kb_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> tuple[list[SourceMaterial], int]:
        """分页列出知识库下的所有资料。"""
        count_stmt = (
            select(func.count())
            .select_from(SourceMaterial)
            .where(SourceMaterial.kb_id == kb_id)
        )
        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            select(SourceMaterial)
            .where(SourceMaterial.kb_id == kb_id)
            .order_by(SourceMaterial.created_at.desc(), SourceMaterial.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all()), total

    async def list_by_kb_with_chunk_stats_page(
        self,
        kb_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[SourceMaterial, int]], int]:
        """分页列出资料并附带分块数量。"""
        count_stmt = (
            select(func.count())
            .select_from(SourceMaterial)
            .where(SourceMaterial.kb_id == kb_id)
        )
        total = int((await self._db.execute(count_stmt)).scalar_one())

        chunk_count = func.count(DocumentChunk.id).label("chunk_count")
        stmt = (
            select(SourceMaterial, chunk_count)
            .outerjoin(
                DocumentChunk,
                and_(
                    DocumentChunk.material_id == SourceMaterial.id,
                    DocumentChunk.kb_id == SourceMaterial.kb_id,
                ),
            )
            .where(SourceMaterial.kb_id == kb_id)
            .group_by(SourceMaterial.id)
            .order_by(SourceMaterial.created_at.desc(), SourceMaterial.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        rows = result.all()
        return [(material, int(cnt or 0)) for material, cnt in rows], total

    async def list_chunks_by_material_page(
        self,
        *,
        kb_id: uuid.UUID,
        material_id: uuid.UUID,
        skip: int = 0,
        limit: int = 200,
    ) -> tuple[list[DocumentChunk], int]:
        """分页列出指定资料的分块（稳定顺序）。"""
        count_stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.kb_id == kb_id,
                DocumentChunk.material_id == material_id,
            )
        )
        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.kb_id == kb_id,
                DocumentChunk.material_id == material_id,
            )
            .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_chunk_by_id(
        self,
        *,
        kb_id: uuid.UUID,
        material_id: uuid.UUID,
        chunk_id: uuid.UUID,
    ) -> DocumentChunk | None:
        """按知识库/资料范围获取单个分块。"""
        stmt = select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.kb_id == kb_id,
            DocumentChunk.material_id == material_id,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, material_id: uuid.UUID) -> SourceMaterial | None:
        """根据 ID 获取资料。"""
        return await self._db.get(SourceMaterial, material_id)

    async def get_by_ids(self, material_ids: list[uuid.UUID]) -> list[SourceMaterial]:
        """根据 ID 列表获取资料。"""
        if not material_ids:
            return []
        stmt = select(SourceMaterial).where(SourceMaterial.id.in_(material_ids))
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def create_text(
        self, kb_id: uuid.UUID, title: str, text: str
    ) -> SourceMaterial:
        """创建文本资料。"""
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:32]
        material = SourceMaterial(
            kb_id=kb_id,
            source_type=SourceType.TEXT,
            title=title,
            content_hash=content_hash,
            metadata_={"text": text},
        )
        self._db.add(material)
        await self._db.commit()
        await self._db.refresh(material)
        return material

    async def create_url(
        self, kb_id: uuid.UUID, title: str, url: str
    ) -> SourceMaterial:
        """创建 URL 资料。"""
        validated_url = await self._url_guard.validate_source_url(url)
        content_hash = hashlib.sha256(validated_url.encode()).hexdigest()[:32]
        material = SourceMaterial(
            kb_id=kb_id,
            source_type=SourceType.URL,
            title=title,
            uri=validated_url,
            content_hash=content_hash,
        )
        self._db.add(material)
        await self._db.commit()
        await self._db.refresh(material)
        return material

    async def upload_file(
        self,
        kb_id: uuid.UUID,
        title: str,
        file: BinaryIO,
        filename: str,
        content_type: str | None = None,
    ) -> SourceMaterial:
        """上传文件资料到 MinIO。"""
        settings = self._settings
        file_content = await asyncio.to_thread(file.read)

        # 验证文件大小和类型
        validate_file_upload(file_content, filename, content_type)

        content_hash = hashlib.sha256(file_content).hexdigest()[:32]

        # 生成对象存储路径
        material_id = uuid.uuid4()
        object_name = f"{kb_id}/{material_id}/{filename}"
        ref = ObjectRef(bucket=settings.minio_bucket_uploads, object_name=object_name)

        # 上传到 MinIO
        await self._storage.ensure_buckets()
        await self._storage.put_bytes(ref, file_content, content_type=content_type)

        # 创建资料记录
        material = SourceMaterial(
            id=material_id,
            kb_id=kb_id,
            source_type=SourceType.UPLOAD,
            title=title,
            uri=f"minio://{ref.bucket}/{ref.object_name}",
            mime_type=content_type,
            content_hash=content_hash,
        )
        self._db.add(material)
        await self._db.commit()
        await self._db.refresh(material)
        return material
