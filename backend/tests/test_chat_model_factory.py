from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.integrations.chat_model_factory import (
    _resolve_model_name,
    _supports_ollama_reasoning_level,
    create_chat_model,
)
from app.integrations.model_runtime_config import (
    ModelRuntimeConfigManager,
    RuntimeModelSnapshot,
    RuntimeProviderConfig,
)
from app.models.model_config import ModelProvider


def test_supports_ollama_reasoning_level_for_gpt_oss_models() -> None:
    assert _supports_ollama_reasoning_level("gpt-oss:20b")
    assert _supports_ollama_reasoning_level(" openai/gpt-oss-120b ")


def test_supports_ollama_reasoning_level_rejects_non_gpt_oss_models() -> None:
    assert not _supports_ollama_reasoning_level("qwen2.5:7b")
    assert not _supports_ollama_reasoning_level("llama3.1")


def test_resolve_model_name_requires_configured_models() -> None:
    with pytest.raises(RuntimeError, match="模型配置不完整"):
        _resolve_model_name(
            provider=ModelProvider.OLLAMA,
            snapshot_model=None,
            provider_models=[],
        )

    with pytest.raises(RuntimeError, match="模型配置不完整"):
        _resolve_model_name(
            provider=ModelProvider.OPENAI,
            snapshot_model=None,
            provider_models=[],
        )


def test_resolve_model_name_prefers_provider_model_list_when_snapshot_empty() -> None:
    model_name = _resolve_model_name(
        provider=ModelProvider.OLLAMA,
        snapshot_model=None,
        provider_models=["qwen2.5:14b", "qwen2.5:7b"],
    )
    assert model_name == "qwen2.5:14b"


def test_create_chat_model_openai_thinking_enables_responses_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=_FakeChatOpenAI))

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.OPENAI,
        enabled=True,
        base_url="https://api.openai.com/v1",
        api_key="provider-key",
        models=["gpt-4.1-mini"],
        thinking_enabled=True,
        thinking_level="high",
    )
    snapshot = RuntimeModelSnapshot(
        providers={ModelProvider.OPENAI: provider_cfg},
        active_provider=ModelProvider.OPENAI,
        active_model="gpt-4.1-mini",
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(ModelRuntimeConfigManager, "_snapshot", snapshot)

    settings = SimpleNamespace(
        llm_timeout_seconds=30.0,
        llm_max_input_tokens=None,
        llm_output_version="responses/v1",
    )

    model = create_chat_model(settings=settings)
    assert isinstance(model, _FakeChatOpenAI)
    assert captured_kwargs["output_version"] == "responses/v1"
    assert captured_kwargs["use_responses_api"] is True
    assert captured_kwargs["use_previous_response_id"] is True
    assert captured_kwargs["reasoning"] == {"effort": "high", "summary": "auto"}


def test_create_chat_model_openai_allows_disabling_previous_response_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    )

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.OPENAI,
        enabled=True,
        base_url="https://api.openai.com/v1",
        api_key="provider-key",
        models=["gpt-4.1-mini"],
        thinking_enabled=True,
        thinking_level="high",
    )
    snapshot = RuntimeModelSnapshot(
        providers={ModelProvider.OPENAI: provider_cfg},
        active_provider=ModelProvider.OPENAI,
        active_model="gpt-4.1-mini",
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(ModelRuntimeConfigManager, "_snapshot", snapshot)

    settings = SimpleNamespace(
        llm_timeout_seconds=30.0,
        llm_max_input_tokens=None,
        llm_output_version="responses/v1",
    )

    model = create_chat_model(
        settings=settings,
        use_previous_response_id=False,
    )
    assert isinstance(model, _FakeChatOpenAI)
    assert captured_kwargs["use_previous_response_id"] is False
    assert captured_kwargs["use_responses_api"] is True


def test_create_chat_model_openai_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.OPENAI,
        enabled=True,
        base_url="https://api.openai.com/v1",
        api_key=None,
        models=["gpt-4.1-mini"],
        thinking_enabled=True,
        thinking_level="high",
    )
    snapshot = RuntimeModelSnapshot(
        providers={ModelProvider.OPENAI: provider_cfg},
        active_provider=ModelProvider.OPENAI,
        active_model="gpt-4.1-mini",
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(ModelRuntimeConfigManager, "_snapshot", snapshot)
    settings = SimpleNamespace(
        llm_timeout_seconds=30.0,
        llm_max_input_tokens=None,
        llm_output_version="responses/v1",
    )

    with pytest.raises(RuntimeError, match="API Key 未配置"):
        create_chat_model(settings=settings)


def test_create_chat_model_openai_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.OPENAI,
        enabled=True,
        base_url=None,
        api_key="provider-key",
        models=["gpt-4.1-mini"],
        thinking_enabled=True,
        thinking_level="high",
    )
    snapshot = RuntimeModelSnapshot(
        providers={ModelProvider.OPENAI: provider_cfg},
        active_provider=ModelProvider.OPENAI,
        active_model="gpt-4.1-mini",
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(ModelRuntimeConfigManager, "_snapshot", snapshot)
    settings = SimpleNamespace(
        llm_timeout_seconds=30.0,
        llm_max_input_tokens=None,
        llm_output_version="responses/v1",
    )

    with pytest.raises(RuntimeError, match="Base URL 未配置"):
        create_chat_model(settings=settings)
