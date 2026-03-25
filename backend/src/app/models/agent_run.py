"""智能体运行记录 ORM 模型。"""

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
    from app.models.chat_session import ChatSession
    from app.models.evidence import Evidence


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentRunType(str, Enum):
    KB_ANSWER = "kb_answer"
    GENERAL_ANSWER = "general_answer"


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_type: Mapped[AgentRunType] = mapped_column(
        enum_values(AgentRunType, name="agent_run_type"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    selected_kb_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=True
    )
    allow_external: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    mode: Mapped[AgentMode] = mapped_column(
        enum_values(AgentMode, name="agent_mode", create_type=False), nullable=False
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        enum_values(AgentRunStatus, name="agent_run_status"),
        nullable=False,
        default=AgentRunStatus.RUNNING,
    )
    stage_summaries: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_output: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
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

    # 关系
    session: Mapped["ChatSession | None"] = relationship(
        "ChatSession", back_populates="runs"
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="run", lazy="selectin"
    )
