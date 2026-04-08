from __future__ import annotations

from app.models.model_config import ModelProvider
from app.services.model_config_service import (
    _default_thinking_level,
    _normalize_provider_base_url,
)


def test_normalize_anthropic_messages_endpoint_to_root_url() -> None:
    assert (
        _normalize_provider_base_url(
            ModelProvider.ANTHROPIC,
            "http://example/v1/messages/",
        )
        == "http://example"
    )


def test_non_anthropic_provider_keeps_openai_style_v1_base_url() -> None:
    assert (
        _normalize_provider_base_url(
            ModelProvider.OPENAI,
            "https://api.openai.com/v1/",
        )
        == "https://api.openai.com/v1"
    )


def test_anthropic_defaults_to_high_thinking_level() -> None:
    assert _default_thinking_level(ModelProvider.ANTHROPIC) == "high"
