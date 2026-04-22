from __future__ import annotations

from app.config.provider_registry import ordered_provider_descriptors
from app.core.settings import Settings, get_settings
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.schemas.public_runtime_config import (
    IngestionManifestConstraintsRead,
    ProviderDescriptorRead,
    PublicRuntimeConfigRead,
)
from app.schemas.chats import default_kb_chat_config, kb_chat_config_constraints
from app.schemas.knowledge_bases import (
    IndexConfig,
    index_config_constraints,
    knowledge_base_form_constraints,
)
from app.services.upload_policy import build_upload_policy_snapshot
from app.services.ingestion_batch_service_contracts import (
    MAX_FILE_ENTRIES,
    MAX_MANIFEST_ENTRIES,
    MAX_TEXT_LENGTH,
    MAX_URL_ENTRIES,
)


def _default_index_config() -> IndexConfig:
    return IndexConfig()


class PublicRuntimeConfigService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def get_runtime_config(self) -> PublicRuntimeConfigRead:
        descriptors = ordered_provider_descriptors()
        settings = self._settings or get_settings()
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=settings)
        upload_policy = build_upload_policy_snapshot()
        return PublicRuntimeConfigRead(
            default_model_provider=snapshot.active_provider,
            status_polling_interval_ms=settings.frontend_status_polling_interval_ms,
            ingestion_stream_fallback_polling_steps_ms=settings.frontend_ingestion_stream_fallback_polling_steps_ms,
            ingestion_stream_retry_multiplier=settings.frontend_ingestion_stream_retry_multiplier,
            export_poll_interval_ms=settings.frontend_export_poll_interval_ms,
            export_poll_max_attempts=settings.frontend_export_poll_max_attempts,
            server_prefetch_cache_revalidate_seconds=settings.frontend_server_prefetch_cache_revalidate_seconds,
            download_allowed_hosts=settings.frontend_download_allowed_hosts,
            kb_chat_default_config=default_kb_chat_config(settings=settings),
            kb_chat_config_constraints=kb_chat_config_constraints(),
            knowledge_base_default_index_config=_default_index_config(),
            knowledge_base_index_config_constraints=index_config_constraints(),
            knowledge_base_form_constraints=knowledge_base_form_constraints(),
            ingestion_manifest_constraints=IngestionManifestConstraintsRead(
                max_entries=MAX_MANIFEST_ENTRIES,
                max_text_length=MAX_TEXT_LENGTH,
                max_url_entries=MAX_URL_ENTRIES,
                max_file_entries=MAX_FILE_ENTRIES,
            ),
            upload_max_file_size_bytes=upload_policy.max_file_size_bytes,
            upload_allowed_extensions=upload_policy.allowed_extensions,
            upload_allowed_mime_types=upload_policy.allowed_mime_types,
            upload_mime_type_aliases=upload_policy.mime_type_aliases,
            upload_generic_mime_types=upload_policy.generic_mime_types,
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
