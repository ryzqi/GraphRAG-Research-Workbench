from __future__ import annotations

from pydantic import BaseModel

from app.models.model_config import ModelProvider


class ProviderDescriptorRead(BaseModel):
    provider: ModelProvider
    label: str
    base_url_placeholder: str
    base_url_helper_text: str | None = None
    supports_thinking_toggle: bool
    supports_thinking_level: bool
    default_thinking_enabled: bool
    default_thinking_level: str | None = None
    api_key_optional: bool
    structured_output_method: str | None = None


class PublicRuntimeConfigRead(BaseModel):
    default_model_provider: ModelProvider
    status_polling_interval_ms: int
    ingestion_stream_fallback_polling_steps_ms: list[int]
    ingestion_stream_retry_multiplier: int
    export_poll_interval_ms: int
    export_poll_max_attempts: int
    server_prefetch_cache_revalidate_seconds: int
    download_allowed_hosts: list[str]
    providers: list[ProviderDescriptorRead]
