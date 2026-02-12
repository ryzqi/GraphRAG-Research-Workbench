"""Research v2 会话 ORM 模型。"""

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
from app.models.chat_session import AgentMode

if TYPE_CHECKING:
    from app.models.research_artifact import ResearchArtifact
    from app.models.research_event import ResearchEvent


class ResearchSessionStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    RESUMED = "resumed"
    FINAL = "final"
    FAILED = "failed"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"


TERMINAL_RESEARCH_SESSION_STATUSES: set[ResearchSessionStatus] = {
    ResearchSessionStatus.FINAL,
    ResearchSessionStatus.FAILED,
    ResearchSessionStatus.CANCELED,
    ResearchSessionStatus.TIMED_OUT,
}


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[str] = mapped_column(sa.String(length=128), nullable=False, unique=True)
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    selected_kb_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=True
    )
    allow_external: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    mode: Mapped[AgentMode] = mapped_column(
        enum_values(AgentMode, name="agent_mode", create_type=False), nullable=False
    )
    status: Mapped[ResearchSessionStatus] = mapped_column(
        enum_values(ResearchSessionStatus, name="research_session_status"),
        nullable=False,
        default=ResearchSessionStatus.CREATED,
    )
    stage_summaries: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_output: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(sa.String(length=128), nullable=True, index=True)
    last_event_sequence: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    last_resume_idempotency_key: Mapped[str | None] = mapped_column(
        sa.String(length=128), nullable=True
    )
    last_resume_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    legacy_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    events: Mapped[list["ResearchEvent"]] = relationship(
        "ResearchEvent",
        back_populates="session",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["ResearchArtifact"]] = relationship(
        "ResearchArtifact",
        back_populates="session",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
