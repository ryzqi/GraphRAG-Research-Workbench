from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import enum_values


class IngestionTaskOutboxStatus(str, Enum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class IngestionTaskOutbox(Base):
    __tablename__ = "ingestion_task_outbox"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_batch_docs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    status: Mapped[IngestionTaskOutboxStatus] = mapped_column(
        enum_values(IngestionTaskOutboxStatus, name="ingestion_task_outbox_status"),
        nullable=False,
        default=IngestionTaskOutboxStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=20,
        server_default=sa.text("20"),
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint("doc_id", "task_name", name="uq_ingestion_task_outbox_doc_task"),
        sa.Index(
            "ix_ingestion_task_outbox_status_next_retry_created",
            "status",
            "next_retry_at",
            "created_at",
        ),
    )
