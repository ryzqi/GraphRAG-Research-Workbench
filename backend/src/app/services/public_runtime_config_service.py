from __future__ import annotations

from app.config.provider_registry import ordered_provider_descriptors
from app.core.settings import Settings, get_settings
from app.models.model_config import ModelProvider
from app.schemas.public_runtime_config import (
    ProviderDescriptorRead,
    PublicRuntimeConfigRead,
)


class PublicRuntimeConfigService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def get_runtime_config(self) -> PublicRuntimeConfigRead:
        descriptors = ordered_provider_descriptors()
        settings = self._settings or get_settings()
        return PublicRuntimeConfigRead(
            default_model_provider=ModelProvider.OPENAI,
            status_polling_interval_ms=settings.frontend_status_polling_interval_ms,
            ingestion_stream_fallback_polling_steps_ms=settings.frontend_ingestion_stream_fallback_polling_steps_ms,
            ingestion_stream_retry_multiplier=settings.frontend_ingestion_stream_retry_multiplier,
            export_poll_interval_ms=settings.frontend_export_poll_interval_ms,
            export_poll_max_attempts=settings.frontend_export_poll_max_attempts,
            server_prefetch_cache_revalidate_seconds=settings.frontend_server_prefetch_cache_revalidate_seconds,
            download_allowed_hosts=settings.frontend_download_allowed_hosts,
            providers=[
                ProviderDescriptorRead(
                    provider=item.provider,
                    label=item.label,
                    base_url_placeholder=item.base_url_placeholder,
                    base_url_helper_text=item.base_url_helper_text,
                    supports_thinking_toggle=item.supports_thinking_toggle,
                    supports_thinking_level=item.supports_thinking_level,
                    default_thinking_enabled=item.default_thinking_enabled,
                    default_thinking_level=item.default_thinking_level,
                    api_key_optional=item.api_key_optional,
                    structured_output_method=item.structured_output_method,
                )
                for item in descriptors
            ],
        )
