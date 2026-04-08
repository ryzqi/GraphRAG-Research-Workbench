from __future__ import annotations

import sys
from types import SimpleNamespace

from app.integrations.chat_model_factory import create_chat_model_from_runtime_config
from app.integrations.model_health_probe import _map_probe_exception
from app.integrations.model_runtime_config import RuntimeProviderConfig
from app.models.model_config import ModelProvider


def test_create_chat_model_uses_chat_anthropic(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_anthropic",
        SimpleNamespace(ChatAnthropic=FakeChatAnthropic),
    )

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.ANTHROPIC,
        enabled=True,
        base_url="http://example",
        api_key="sk-test",
        models=["claude-sonnet-4-6"],
        thinking_enabled=True,
        thinking_level="high",
    )

    create_chat_model_from_runtime_config(
        provider_cfg=provider_cfg,
        model_name="claude-sonnet-4-6",
    )

    assert captured["base_url"] == "http://example"
    assert captured["api_key"] == "sk-test"
    assert captured["effort"] == "high"


def test_map_anthropic_auth_failure_to_app_error() -> None:
    class AuthenticationError(Exception):
        status_code = 401

    AuthenticationError.__module__ = "anthropic"

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.ANTHROPIC,
        enabled=True,
        base_url="http://example",
        api_key="sk-test",
        models=["claude-sonnet-4-6"],
        thinking_enabled=True,
        thinking_level="high",
    )

    err = _map_probe_exception(
        exc=AuthenticationError(),
        provider_cfg=provider_cfg,
        model_name="claude-sonnet-4-6",
    )

    assert err.code == "MODEL_PROBE_AUTH_FAILED"
