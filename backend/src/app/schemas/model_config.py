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
    # Response 侧默认值仅用于防御性兼容兜底；
    # 真正的 runtime / bootstrap 默认值位于 model_config_service/runtime_config。
    provider: ModelProvider
    enabled: bool
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)
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
    models: list[str] | None = None
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

    @field_validator("models", mode="before")
    @classmethod
    def _normalize_models(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("models must be a list")

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_item in value:
            raw = str(raw_item).strip()
            if not raw or raw in seen:
                continue
            if len(raw) > 256:
                raise ValueError("model name must be at most 256 characters")
            normalized.append(raw)
            seen.add(raw)
        return normalized

    @field_validator("thinking_level", mode="before")
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
