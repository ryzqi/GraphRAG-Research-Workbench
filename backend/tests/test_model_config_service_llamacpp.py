from __future__ import annotations

from app.models.model_config import ModelProvider
from app.services.model_config_service import (
    _PROVIDER_ORDER,
    _default_thinking_level,
    _normalize_provider_base_url,
)


def test_normalize_llamacpp_root_url_to_v1() -> None:
    assert (
        _normalize_provider_base_url(
            ModelProvider.LLAMA_CPP,
            "http://127.0.0.1:8080",
        )
        == "http://127.0.0.1:8080/v1"
    )


def test_normalize_llamacpp_chat_completions_url_to_v1() -> None:
    assert (
        _normalize_provider_base_url(
            ModelProvider.LLAMA_CPP,
            "http://127.0.0.1:8080/v1/chat/completions",
        )
        == "http://127.0.0.1:8080/v1"
    )


def test_provider_order_contains_llamacpp() -> None:
    assert ModelProvider.LLAMA_CPP in _PROVIDER_ORDER


def test_llamacpp_default_thinking_level_is_none() -> None:
    assert _default_thinking_level(ModelProvider.LLAMA_CPP) is None
