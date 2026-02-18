from __future__ import annotations

import pytest

from app.integrations.chat_model_factory import (
    _resolve_model_name,
    _supports_ollama_reasoning_level,
)
from app.models.model_config import ModelProvider


def test_supports_ollama_reasoning_level_for_gpt_oss_models() -> None:
    assert _supports_ollama_reasoning_level("gpt-oss:20b")
    assert _supports_ollama_reasoning_level(" openai/gpt-oss-120b ")


def test_supports_ollama_reasoning_level_rejects_non_gpt_oss_models() -> None:
    assert not _supports_ollama_reasoning_level("qwen2.5:7b")
    assert not _supports_ollama_reasoning_level("llama3.1")


def test_resolve_model_name_uses_openai_fallback_only_for_openai() -> None:
    openai_model = _resolve_model_name(
        provider=ModelProvider.OPENAI,
        snapshot_model=None,
        provider_models=[],
        fallback_openai_model="gpt-4o-mini",
    )
    assert openai_model == "gpt-4o-mini"

    with pytest.raises(RuntimeError, match="No model configured for provider: ollama"):
        _resolve_model_name(
            provider=ModelProvider.OLLAMA,
            snapshot_model=None,
            provider_models=[],
            fallback_openai_model="gpt-4o-mini",
        )


def test_resolve_model_name_prefers_provider_model_list_when_snapshot_empty() -> None:
    model_name = _resolve_model_name(
        provider=ModelProvider.OLLAMA,
        snapshot_model=None,
        provider_models=["qwen2.5:14b", "qwen2.5:7b"],
        fallback_openai_model="gpt-4o-mini",
    )
    assert model_name == "qwen2.5:14b"
