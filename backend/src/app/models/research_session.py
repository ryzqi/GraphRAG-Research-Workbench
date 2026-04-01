"""深度研究会话 ORM 模型。"""

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
    from app.models.research_artifact import ResearchArtifact
    from app.models.research_event import ResearchEvent


class ResearchSessionStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    CLARIFYING = "clarifying"
    QUEUED = "queued"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    RESUMING = "resuming"
    FINALIZING = "finalizing"
    FINAL = "final"
    FAILED = "failed"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"

    def is_terminal(self) -> bool:
        return self in _TERMINAL_RESEARCH_SESSION_STATUSES

    def can_transition_to(self, target: "ResearchSessionStatus") -> bool:
        if self == target:
            return True
        if self.is_terminal():
            return False
        return target in _ALLOWED_RESEARCH_SESSION_TRANSITIONS[self]


_TERMINAL_RESEARCH_SESSION_STATUSES = frozenset(
    {
        ResearchSessionStatus.FINAL,
        ResearchSessionStatus.FAILED,
        ResearchSessionStatus.CANCELED,
        ResearchSessionStatus.TIMED_OUT,
    }
)

_ALLOWED_RESEARCH_SESSION_TRANSITIONS: dict[
    ResearchSessionStatus, frozenset[ResearchSessionStatus]
] = {
    ResearchSessionStatus.CREATED: frozenset(
        {
            ResearchSessionStatus.PLANNING,
            ResearchSessionStatus.QUEUED,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.PLANNING: frozenset(
        {
            ResearchSessionStatus.CLARIFYING,
            ResearchSessionStatus.QUEUED,
            ResearchSessionStatus.RUNNING,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.CLARIFYING: frozenset(
        {
            ResearchSessionStatus.QUEUED,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.QUEUED: frozenset(
        {
            ResearchSessionStatus.RUNNING,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.RUNNING: frozenset(
        {
            ResearchSessionStatus.INTERRUPTED,
            ResearchSessionStatus.FINALIZING,
            ResearchSessionStatus.FINAL,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.INTERRUPTED: frozenset(
        {
            ResearchSessionStatus.RESUMING,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.RESUMING: frozenset(
        {
            ResearchSessionStatus.RUNNING,
            ResearchSessionStatus.FINALIZING,
            ResearchSessionStatus.FINAL,
            ResearchSessionStatus.CANCELED,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.FINALIZING: frozenset(
        {
            ResearchSessionStatus.FINAL,
            ResearchSessionStatus.FAILED,
            ResearchSessionStatus.TIMED_OUT,
        }
    ),
    ResearchSessionStatus.FINAL: frozenset(),
    ResearchSessionStatus.FAILED: frozenset(),
    ResearchSessionStatus.CANCELED: frozenset(),
    ResearchSessionStatus.TIMED_OUT: frozenset(),
}


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[str] = mapped_column(sa.String(length=128), nullable=False, unique=True)
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ResearchSessionStatus] = mapped_column(
        enum_values(ResearchSessionStatus, name="research_session_status"),
        nullable=False,
        default=ResearchSessionStatus.CREATED,
        server_default=ResearchSessionStatus.CREATED.value,
        index=True,
    )
    planner_phase: Mapped[str | None] = mapped_column(sa.String(length=64), nullable=True)
    runtime_phase: Mapped[str | None] = mapped_column(sa.String(length=64), nullable=True)
    finalizer_phase: Mapped[str | None] = mapped_column(sa.String(length=64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(sa.String(length=128), nullable=True, index=True)
    last_event_sequence: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    last_resume_idempotency_key: Mapped[str | None] = mapped_column(
        sa.String(length=128), nullable=True
    )
    last_resume_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    events: Mapped[list["ResearchEvent"]] = relationship(
        "ResearchEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    artifacts: Mapped[list["ResearchArtifact"]] = relationship(
        "ResearchArtifact",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def transition_to(self, target: ResearchSessionStatus) -> None:
        if not self.status.can_transition_to(target):
            raise ValueError(
                f"终态或非法状态迁移: {self.status.value} -> {target.value}"
            )
        self.status = target
