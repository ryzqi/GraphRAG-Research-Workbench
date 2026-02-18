"""模型配置相关 Schema。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelProvider(str, Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    NVIDIA = "nvidia"


class ProviderConfigRead(BaseModel):
    provider: ModelProvider
    enabled: bool
    base_url: str | None = None
    model: str | None = None
    thinking_enabled: bool = True
    thinking_level: str | None = None
    api_key_set: bool = False
    api_key_masked: str | None = None
    updated_at: datetime | None = None


class ModelConfigRead(BaseModel):
    providers: list[ProviderConfigRead]
    active_provider: ModelProvider
    active_model: str | None = None
    updated_at: datetime | None = None


class ProviderConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = Field(None, max_length=256)
    thinking_enabled: bool | None = None
    thinking_level: str | None = Field(None, max_length=32)

    @field_validator("base_url", mode="before")
    @classmethod
    def _normalize_base_url(cls, value: object) -> object:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        return raw.rstrip("/")

    @field_validator("model", "thinking_level", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        raw = str(value).strip()
        return raw or None


class ActiveModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ModelProvider
    model: str | None = Field(None, max_length=256)

    @field_validator("model", mode="before")
    @classmethod
    def _normalize_model(cls, value: object) -> object:
        if value is None:
            return None
        raw = str(value).strip()
        return raw or None
