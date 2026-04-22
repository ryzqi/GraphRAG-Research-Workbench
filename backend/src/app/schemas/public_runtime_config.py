from __future__ import annotations

from pydantic import BaseModel

from app.models.model_config import ModelProvider
from app.schemas.chats import KbChatConfig, KbChatConfigConstraints
from app.schemas.knowledge_bases import (
    IndexConfig,
    IndexConfigConstraints,
    KnowledgeBaseFormConstraints,
)


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


class IngestionManifestConstraintsRead(BaseModel):
    max_entries: int
    max_text_length: int
    max_url_entries: int
    max_file_entries: int


class PublicRuntimeConfigRead(BaseModel):
    default_model_provider: ModelProvider
    status_polling_interval_ms: int
    ingestion_stream_fallback_polling_steps_ms: list[int]
    ingestion_stream_retry_multiplier: int
    export_poll_interval_ms: int
    export_poll_max_attempts: int
    server_prefetch_cache_revalidate_seconds: int
    download_allowed_hosts: list[str]
    kb_chat_default_config: KbChatConfig
    kb_chat_config_constraints: KbChatConfigConstraints
    knowledge_base_default_index_config: IndexConfig
    knowledge_base_index_config_constraints: IndexConfigConstraints
    knowledge_base_form_constraints: KnowledgeBaseFormConstraints
    ingestion_manifest_constraints: IngestionManifestConstraintsRead
    upload_max_file_size_bytes: int
    upload_allowed_extensions: list[str]
    upload_allowed_mime_types: list[str]
    upload_mime_type_aliases: dict[str, str]
    upload_generic_mime_types: list[str]
    providers: list[ProviderDescriptorRead]
