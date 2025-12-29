"""扩展调用记录 ORM 模型。"""

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
    from app.models.agent_run import AgentRun
    from app.models.tool_extension import ToolExtension


class InvocationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("tool_extensions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    purpose: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[InvocationStatus] = mapped_column(
        sa.Enum(InvocationStatus, name="invocation_status"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    user_confirmed: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # 关系
    extension: Mapped["ToolExtension"] = relationship(
        "ToolExtension", back_populates="invocations"
    )
    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="tool_invocations")
