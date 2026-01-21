"""对话会话 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import enum_values

if TYPE_CHECKING:
    from app.models.agent_run import AgentRun
    from app.models.chat_message import ChatMessage


class ChatSessionType(str, Enum):
    KB_CHAT = "kb_chat"
    GENERAL_CHAT = "general_chat"


class AgentMode(str, Enum):
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT = "multi_agent"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_type: Mapped[ChatSessionType] = mapped_column(
        enum_values(ChatSessionType, name="chat_session_type"), nullable=False
    )
    selected_kb_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=True
    )
    allow_external: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    mode: Mapped[AgentMode] = mapped_column(
        enum_values(AgentMode, name="agent_mode"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    # 关系
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        lazy="selectin",
        order_by="ChatMessage.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun", back_populates="session", lazy="selectin"
    )
