"""深度研究工件 ORM 模型。"""

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


class ResearchArtifact(Base):
    __tablename__ = "research_artifacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "session_id",
            "artifact_key",
            name="uq_research_artifacts_session_key",
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
    artifact_key: Mapped[str] = mapped_column(sa.String(length=64), nullable=False)
    content_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    content_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    source_type: Mapped[str | None] = mapped_column(sa.String(length=32), nullable=True)
    source_provider: Mapped[str | None] = mapped_column(
        sa.String(length=64), nullable=True
    )
    retrieval_method: Mapped[str | None] = mapped_column(
        sa.String(length=64), nullable=True
    )
    origin_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    session: Mapped["ResearchSession"] = relationship(
        "ResearchSession", back_populates="artifacts"
    )
