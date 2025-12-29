"""反馈 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent_run import AgentRun


class FeedbackStatus(str, Enum):
    """反馈处理状态。"""

    PENDING = "pending"  # 待处理
    REVIEWED = "reviewed"  # 已查看
    RESOLVED = "resolved"  # 已解决
    DISMISSED = "dismissed"  # 已忽略


class Feedback(Base):
    """用户反馈记录。"""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, comment="评分 1-5"
    )
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[FeedbackStatus] = mapped_column(
        sa.Enum(FeedbackStatus, name="feedback_status"),
        nullable=False,
        default=FeedbackStatus.PENDING,
    )
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now()
    )

    # 关系
    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="feedback")
