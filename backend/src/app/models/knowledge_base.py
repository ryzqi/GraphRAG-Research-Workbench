"""知识库 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import enum_values

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk
    from app.models.ingestion_job import IngestionJob
    from app.models.index_rebuild_job import IndexRebuildJob
    from app.models.source_material import SourceMaterial


class KnowledgeBaseStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text), nullable=True)
    index_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[KnowledgeBaseStatus] = mapped_column(
        enum_values(KnowledgeBaseStatus, name="knowledge_base_status"),
        nullable=False,
        default=KnowledgeBaseStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    # 关系
    materials: Mapped[list["SourceMaterial"]] = relationship(
        "SourceMaterial", back_populates="knowledge_base", lazy="selectin"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="knowledge_base", lazy="selectin"
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        "IngestionJob", back_populates="knowledge_base", lazy="selectin"
    )
    index_rebuild_jobs: Mapped[list["IndexRebuildJob"]] = relationship(
        "IndexRebuildJob", back_populates="knowledge_base", lazy="selectin"
    )
