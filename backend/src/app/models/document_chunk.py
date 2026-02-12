"""文档切片 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.source_material import SourceMaterial


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("source_materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    context_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    context_status: Mapped[str] = mapped_column(
        sa.String(24), nullable=False, default="not_enabled", server_default="not_enabled"
    )
    context_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    context_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    chunking_strategy: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="unknown", server_default="unknown"
    )
    heading_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    global_chunk_order: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    window_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    window_size_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    window_overlap_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    token_start: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    token_end: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_kind: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    source_page_start: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    locator: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    token_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    # 关系
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="chunks"
    )
    material: Mapped["SourceMaterial"] = relationship(
        "SourceMaterial", back_populates="chunks"
    )

    __table_args__ = (
        sa.Index("ix_document_chunks_kb_material_idx", "kb_id", "material_id", "chunk_index"),
        sa.Index(
            "ix_document_chunks_kb_material_global_order",
            "kb_id",
            "material_id",
            "global_chunk_order",
        ),
        sa.Index(
            "ix_document_chunks_kb_material_window_token",
            "kb_id",
            "material_id",
            "window_id",
            "token_start",
        ),
    )
