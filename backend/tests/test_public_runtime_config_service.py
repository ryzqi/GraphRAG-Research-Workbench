from __future__ import annotations

import pytest

from app.models.model_config import ModelProvider
from app.schemas.chats import KbChatConfig
from app.schemas.knowledge_bases import IndexConfig
from app.services.public_runtime_config_service import PublicRuntimeConfigService


@pytest.mark.asyncio
async def test_public_runtime_config_exposes_shared_defaults() -> None:
    service = PublicRuntimeConfigService()

    config = await service.get_runtime_config()
    kb_defaults = KbChatConfig()
    index_defaults = IndexConfig()

    assert config.default_model_provider == ModelProvider.OPENAI
    assert config.kb_chat_default_config.retrieval_rerank_top_k == 40
    assert config.kb_chat_config_constraints.retrieval_top_k.min == 1
    assert config.kb_chat_config_constraints.retrieval_top_k.max == 20
    assert config.kb_chat_config_constraints.retrieval_rerank_top_k.max == 40
    assert (
        config.kb_chat_default_config.retrieval_parent_max_parents
        == kb_defaults.retrieval_parent_max_parents
    )
    assert (
        config.kb_chat_default_config.retrieval_multiscale_max_chunks_per_document
        == kb_defaults.retrieval_multiscale_max_chunks_per_document
    )
    assert config.knowledge_base_default_index_config == index_defaults
    assert config.knowledge_base_index_config_constraints.markdown_heading.max_heading_level.max == 6
    assert (
        config.knowledge_base_index_config_constraints.query_dependent_multiscale.window_count_max
        == 5
    )
    assert config.knowledge_base_form_constraints.name.min_length == 1
    assert config.knowledge_base_form_constraints.name.max_length == 64
    assert config.knowledge_base_form_constraints.description.min_length is None
    assert config.knowledge_base_form_constraints.description.max_length == 500
    assert config.ingestion_manifest_constraints.max_entries == 100
    assert config.ingestion_manifest_constraints.max_text_length == 200_000
    assert config.ingestion_manifest_constraints.max_url_entries == 50
    assert config.ingestion_manifest_constraints.max_file_entries == 50
    assert config.upload_max_file_size_bytes == 50 * 1024 * 1024
    assert config.upload_allowed_extensions == [".docx", ".md", ".pdf", ".txt"]
    assert config.upload_mime_type_aliases["text/x-markdown"] == "text/markdown"
