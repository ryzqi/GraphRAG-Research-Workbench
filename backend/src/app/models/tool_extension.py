"""MCP 扩展 ORM 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import enum_values

class ExtensionTransport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


class ExtensionStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ToolExtension(Base):
    __tablename__ = "tool_extensions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    transport: Mapped[ExtensionTransport] = mapped_column(
        enum_values(ExtensionTransport, name="extension_transport"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ExtensionStatus] = mapped_column(
        enum_values(ExtensionStatus, name="extension_status"),
        nullable=False,
        default=ExtensionStatus.DISABLED,
    )
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
