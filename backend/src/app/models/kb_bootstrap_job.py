from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import enum_values


class KBBootstrapJobStatus(str, Enum):
    QUEUED_UPLOAD = "queued_upload"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class KBBootstrapJob(Base):
    __tablename__ = "kb_bootstrap_jobs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(sa.String(length=128), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(sa.String(length=128), nullable=True)
    status: Mapped[KBBootstrapJobStatus] = mapped_column(
        enum_values(KBBootstrapJobStatus, name="kb_bootstrap_job_status"),
        nullable=False,
        default=KBBootstrapJobStatus.QUEUED,
    )
    total_entries: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    accepted_entries: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    failed_entries: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    payload_entries: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    upload_manifest: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    entry_errors: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(length=64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
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
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (sa.UniqueConstraint("request_id", name="uq_kb_bootstrap_jobs_request_id"),)
