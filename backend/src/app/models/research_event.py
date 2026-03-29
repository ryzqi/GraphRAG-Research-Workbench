"""深度研究事件 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.research_session import ResearchSession


class ResearchEvent(Base):
    __tablename__ = "research_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "session_id",
            "event_id",
            name="uq_research_events_session_event_id",
        ),
        sa.UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_research_events_session_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[str] = mapped_column(sa.String(length=128), nullable=False)
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(length=64), nullable=False)
    phase: Mapped[str] = mapped_column(sa.String(length=64), nullable=False)
    namespace: Mapped[str] = mapped_column(
        sa.String(length=255),
        nullable=False,
        default="main",
        server_default="main",
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(sa.String(length=128), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(length=128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    session: Mapped["ResearchSession"] = relationship("ResearchSession", back_populates="events")

