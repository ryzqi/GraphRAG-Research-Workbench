from __future__ import annotations

from app.models.model_config import ModelProvider
from app.services.public_runtime_config_service import PublicRuntimeConfigService


def test_provider_registry_keeps_single_source_of_truth_for_order_and_capabilities() -> None:
    from app.config.provider_registry import get_provider_descriptor, ordered_provider_descriptors

    ordered = ordered_provider_descriptors()

    assert [item.provider for item in ordered] == [
        ModelProvider.OPENAI,
        ModelProvider.OLLAMA,
        ModelProvider.LLAMA_CPP,
        ModelProvider.NVIDIA,
        ModelProvider.ANTHROPIC,
    ]

    llama_cpp = get_provider_descriptor(ModelProvider.LLAMA_CPP)
    assert llama_cpp.api_key_optional is True
    assert llama_cpp.supports_thinking_toggle is False
    assert llama_cpp.supports_thinking_level is False

    nvidia = get_provider_descriptor(ModelProvider.NVIDIA)
    assert nvidia.supports_thinking_toggle is True
    assert nvidia.supports_thinking_level is False


async def test_public_runtime_config_service_exposes_provider_descriptors() -> None:
    service = PublicRuntimeConfigService()

    config = await service.get_runtime_config()

    assert config.default_model_provider == ModelProvider.OPENAI
    assert config.status_polling_interval_ms == 2000
    assert config.ingestion_stream_fallback_polling_steps_ms == [1000, 2000, 5000]
    assert config.ingestion_stream_retry_multiplier == 2
    assert config.export_poll_interval_ms == 1000
    assert config.export_poll_max_attempts == 60
    assert config.server_prefetch_cache_revalidate_seconds == 30
    assert config.download_allowed_hosts == []
    assert [item.provider for item in config.providers] == [
        ModelProvider.OPENAI,
        ModelProvider.OLLAMA,
        ModelProvider.LLAMA_CPP,
        ModelProvider.NVIDIA,
        ModelProvider.ANTHROPIC,
    ]

    ollama = next(item for item in config.providers if item.provider == ModelProvider.OLLAMA)
    assert "127.0.0.1" not in ollama.base_url_placeholder
    assert ollama.base_url_placeholder.endswith(":11434")

    anthropic = next(item for item in config.providers if item.provider == ModelProvider.ANTHROPIC)
    assert anthropic.label == "Anthropic"
    assert anthropic.supports_thinking_level is True
    assert anthropic.base_url_helper_text is not None
