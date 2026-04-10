"""模型配置 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import enum_values


class ModelProvider(str, Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama.cpp"
    NVIDIA = "nvidia"
    ANTHROPIC = "anthropic"


class ModelProviderConfig(Base):
    __tablename__ = "model_provider_configs"

    provider: Mapped[ModelProvider] = mapped_column(
        enum_values(ModelProvider, name="model_provider"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    base_url: Mapped[str | None] = mapped_column(sa.String(2048), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    models: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(256)),
        nullable=False,
        default=list,
        server_default=sa.text("'{}'::character varying[]"),
    )
    thinking_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    thinking_level: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class ModelRuntimeSelection(Base):
    __tablename__ = "model_runtime_selection"

    id: Mapped[int] = mapped_column(
        sa.Integer,
        primary_key=True,
        default=1,
        server_default=sa.text("1"),
    )
    active_provider: Mapped[ModelProvider] = mapped_column(
        enum_values(ModelProvider, name="model_provider"),
        nullable=False,
        default=ModelProvider.OPENAI,
        server_default=sa.text("'openai'::model_provider"),
    )
    active_model: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
