from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import enum_values

if TYPE_CHECKING:
    from app.models.kb_config_snapshot import KBConfigSnapshot
    from app.models.knowledge_base import KnowledgeBase


class IngestionBatchStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class IngestionDocStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class IngestionSourceType(str, Enum):
    TEXT = "text"
    URL = "url"
    FILE = "file"


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("kb_config_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    config_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    is_bootstrap: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    status: Mapped[IngestionBatchStatus] = mapped_column(
        enum_values(IngestionBatchStatus, name="ingestion_batch_status"),
        nullable=False,
        default=IngestionBatchStatus.PROCESSING,
    )
    total_docs: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    succeeded_docs: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    failed_docs: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    canceled_docs: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    succeeded_chunks: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    error_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="ingestion_batches"
    )
    config_snapshot: Mapped["KBConfigSnapshot"] = relationship("KBConfigSnapshot")
    docs: Mapped[list["IngestionBatchDoc"]] = relationship(
        "IngestionBatchDoc", back_populates="batch", lazy="selectin"
    )
    events: Mapped[list["IngestionEvent"]] = relationship(
        "IngestionEvent", back_populates="batch", lazy="selectin"
    )

    __table_args__ = (
        sa.Index(
            "uq_ingestion_batches_bootstrap_kb",
            "kb_id",
            unique=True,
            postgresql_where=sa.text("is_bootstrap = true"),
        ),
    )


class IngestionBatchDoc(Base):
    __tablename__ = "ingestion_batch_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("kb_config_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    config_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source_type: Mapped[IngestionSourceType] = mapped_column(
        enum_values(IngestionSourceType, name="ingestion_source_type"),
        nullable=False,
    )
    source_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    status: Mapped[IngestionDocStatus] = mapped_column(
        enum_values(IngestionDocStatus, name="ingestion_doc_status"),
        nullable=False,
        default=IngestionDocStatus.PROCESSING,
    )
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    retryable: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    chunk_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    context_failed_chunks: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True
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

    batch: Mapped["IngestionBatch"] = relationship(
        "IngestionBatch", back_populates="docs"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "kb_id",
            "fingerprint",
            "config_version",
            name="uq_ingestion_batch_docs_idempotency",
        ),
    )


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_batch_docs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    batch: Mapped["IngestionBatch"] = relationship(
        "IngestionBatch", back_populates="events"
    )
