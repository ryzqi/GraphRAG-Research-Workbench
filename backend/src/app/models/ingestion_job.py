"""导入任务 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.source_material import SourceMaterial


class IngestionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class IngestionJobItemAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[IngestionStatus] = mapped_column(
        sa.Enum(IngestionStatus, name="ingestion_status"),
        nullable=False,
        default=IngestionStatus.QUEUED,
    )
    requested_by: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # 关系
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="ingestion_jobs"
    )
    items: Mapped[list["IngestionJobItem"]] = relationship(
        "IngestionJobItem", back_populates="job", lazy="selectin"
    )


class IngestionJobItem(Base):
    """导入任务条目，记录每个资料的导入动作。"""

    __tablename__ = "ingestion_job_items"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("source_materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[IngestionJobItemAction] = mapped_column(
        sa.Enum(IngestionJobItemAction, name="ingestion_job_item_action"),
        nullable=False,
        default=IngestionJobItemAction.CREATE,
    )

    # 关系
    job: Mapped["IngestionJob"] = relationship(
        "IngestionJob", back_populates="items"
    )
    material: Mapped["SourceMaterial"] = relationship("SourceMaterial")
