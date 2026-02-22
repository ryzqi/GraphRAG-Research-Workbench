from __future__ import annotations

import datetime as dt
import sys
import types
import warnings

from app.core.settings import get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.model_runtime_config import (
    ModelRuntimeConfigManager,
    RuntimeModelSnapshot,
    RuntimeProviderConfig,
)
from app.models.model_config import ModelProvider


class _FakeChatNVIDIA:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


class _FakeChatNVIDIAWithBind:
    last_kwargs: dict | None = None
    bind_kwargs: list[dict] = []

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)

    def bind(self, **kwargs):
        type(self).bind_kwargs.append(dict(kwargs))
        return types.SimpleNamespace(bound_kwargs=dict(kwargs))


class _FakeChatNVIDIAWarnsOnInit:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)
        warnings.warn(
            "Found moonshotai/kimi-k2.5 in available_models, but type is unknown and inference may fail.",
            UserWarning,
        )


class _FakeChatNVIDIAWithClientMetadata:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)
        self._client = types.SimpleNamespace(
            model=types.SimpleNamespace(supports_tools=False)
        )


def _build_snapshot(*, model_name: str, thinking_enabled: bool) -> RuntimeModelSnapshot:
    providers = {
        ModelProvider.OPENAI: RuntimeProviderConfig(
            provider=ModelProvider.OPENAI,
            enabled=False,
            base_url=None,
            api_key=None,
            models=[],
            thinking_enabled=True,
            thinking_level="high",
        ),
        ModelProvider.OLLAMA: RuntimeProviderConfig(
            provider=ModelProvider.OLLAMA,
            enabled=False,
            base_url=None,
            api_key=None,
            models=[],
            thinking_enabled=True,
            thinking_level="high",
        ),
        ModelProvider.NVIDIA: RuntimeProviderConfig(
            provider=ModelProvider.NVIDIA,
            enabled=True,
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="nvapi-test-key",
            models=[model_name],
            thinking_enabled=thinking_enabled,
            thinking_level="high" if thinking_enabled else None,
        ),
    }
    return RuntimeModelSnapshot(
        providers=providers,
        active_provider=ModelProvider.NVIDIA,
        active_model=model_name,
        updated_at=dt.datetime.now(dt.timezone.utc),
    )


def test_create_chat_model_uses_official_kimi_chatnvidia_defaults(monkeypatch) -> None:
    snapshot = _build_snapshot(
        model_name="moonshotai/kimi-k2.5",
        thinking_enabled=False,
    )
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda *, settings=None: snapshot,
    )
    monkeypatch.setitem(
        sys.modules,
        "langchain_nvidia_ai_endpoints",
        types.SimpleNamespace(ChatNVIDIA=_FakeChatNVIDIA),
    )

    create_chat_model(settings=get_settings())

    assert _FakeChatNVIDIA.last_kwargs is not None
    assert _FakeChatNVIDIA.last_kwargs["model"] == "moonshotai/kimi-k2.5"
    assert _FakeChatNVIDIA.last_kwargs["api_key"] == "nvapi-test-key"
    assert "nvidia_api_key" not in _FakeChatNVIDIA.last_kwargs
    assert _FakeChatNVIDIA.last_kwargs["temperature"] == 1
    assert _FakeChatNVIDIA.last_kwargs["top_p"] == 1
    assert _FakeChatNVIDIA.last_kwargs["max_completion_tokens"] == 16384


def test_create_chat_model_binds_thinking_for_kimi_when_enabled(monkeypatch) -> None:
    snapshot = _build_snapshot(
        model_name="moonshotai/kimi-k2.5",
        thinking_enabled=True,
    )
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda *, settings=None: snapshot,
    )
    monkeypatch.setitem(
        sys.modules,
        "langchain_nvidia_ai_endpoints",
        types.SimpleNamespace(ChatNVIDIA=_FakeChatNVIDIAWithBind),
    )
    _FakeChatNVIDIAWithBind.bind_kwargs = []

    model = create_chat_model(settings=get_settings())

    assert _FakeChatNVIDIAWithBind.bind_kwargs == [
        {"chat_template_kwargs": {"thinking": True}}
    ]
    assert getattr(model, "bound_kwargs", None) == {
        "chat_template_kwargs": {"thinking": True}
    }


def test_create_chat_model_keeps_non_kimi_nvidia_defaults_unchanged(monkeypatch) -> None:
    snapshot = _build_snapshot(
        model_name="mistralai/mistral-7b-instruct-v0.2",
        thinking_enabled=False,
    )
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda *, settings=None: snapshot,
    )
    monkeypatch.setitem(
        sys.modules,
        "langchain_nvidia_ai_endpoints",
        types.SimpleNamespace(ChatNVIDIA=_FakeChatNVIDIA),
    )

    create_chat_model(settings=get_settings())

    assert _FakeChatNVIDIA.last_kwargs is not None
    assert _FakeChatNVIDIA.last_kwargs["model"] == "mistralai/mistral-7b-instruct-v0.2"
    assert "temperature" not in _FakeChatNVIDIA.last_kwargs
    assert "top_p" not in _FakeChatNVIDIA.last_kwargs
    assert "max_completion_tokens" not in _FakeChatNVIDIA.last_kwargs


def test_create_chat_model_suppresses_kimi_unknown_type_warning(monkeypatch) -> None:
    snapshot = _build_snapshot(
        model_name="moonshotai/kimi-k2.5",
        thinking_enabled=False,
    )
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda *, settings=None: snapshot,
    )
    monkeypatch.setitem(
        sys.modules,
        "langchain_nvidia_ai_endpoints",
        types.SimpleNamespace(ChatNVIDIA=_FakeChatNVIDIAWarnsOnInit),
    )

    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        create_chat_model(settings=get_settings())

    assert not any(
        "type is unknown and inference may fail" in str(record.message)
        for record in warning_records
    )


def test_create_chat_model_marks_kimi_as_supporting_tools(monkeypatch) -> None:
    snapshot = _build_snapshot(
        model_name="moonshotai/kimi-k2.5",
        thinking_enabled=False,
    )
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda *, settings=None: snapshot,
    )
    monkeypatch.setitem(
        sys.modules,
        "langchain_nvidia_ai_endpoints",
        types.SimpleNamespace(ChatNVIDIA=_FakeChatNVIDIAWithClientMetadata),
    )

    model = create_chat_model(settings=get_settings())

    assert getattr(model._client.model, "supports_tools", None) is True
