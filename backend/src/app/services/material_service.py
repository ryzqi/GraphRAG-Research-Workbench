"""资料服务（创建/列表/上传）。"""

from __future__ import annotations

import hashlib
import uuid
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.core.validators import validate_file_upload
from app.integrations.object_storage import ObjectRef, ObjectStorage
from app.models.source_material import SourceMaterial, SourceType


class MaterialService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._storage = ObjectStorage()

    async def list_by_kb(self, kb_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[SourceMaterial]:
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

    async def get_by_id(self, material_id: uuid.UUID) -> SourceMaterial | None:
        """根据 ID 获取资料。"""
        return await self._db.get(SourceMaterial, material_id)

    async def get_by_ids(
        self, material_ids: list[uuid.UUID]
    ) -> list[SourceMaterial]:
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
        content_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
        material = SourceMaterial(
            kb_id=kb_id,
            source_type=SourceType.URL,
            title=title,
            uri=url,
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
        settings = get_settings()
        file_content = file.read()

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
