from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import ModuleType

from app.core.settings import get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.model_runtime_config import (
    ModelRuntimeConfigManager,
    RuntimeModelSnapshot,
    RuntimeProviderConfig,
)
from app.models.model_config import ModelProvider


class _CaptureChatOllama:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


class _CaptureChatOpenAI:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def _build_snapshot(
    provider: ModelProvider,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    thinking_enabled: bool = True,
) -> RuntimeModelSnapshot:
    default_base_url = (
        "http://127.0.0.1:11434"
        if provider == ModelProvider.OLLAMA
        else "https://integrate.api.nvidia.com/v1/"
    )
    default_api_key = "dummy-key" if provider == ModelProvider.NVIDIA else None
    return RuntimeModelSnapshot(
        providers={
            provider: RuntimeProviderConfig(
                provider=provider,
                enabled=True,
                base_url=default_base_url if base_url is None else base_url,
                api_key=default_api_key if api_key is None else api_key,
                models=[model],
                thinking_enabled=thinking_enabled,
                thinking_level="high" if provider == ModelProvider.OLLAMA else None,
            )
        },
        active_provider=provider,
        active_model=model,
        updated_at=datetime.now(timezone.utc),
    )


def test_create_chat_model_passes_profile_to_ollama(monkeypatch) -> None:
    _CaptureChatOllama.last_kwargs = None
    fake_module = ModuleType("langchain_ollama")
    fake_module.ChatOllama = _CaptureChatOllama
    monkeypatch.setitem(sys.modules, "langchain_ollama", fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(
            lambda cls, *, settings=None: _build_snapshot(
                ModelProvider.OLLAMA, "kimi-k2.5:cloud"
            )
        ),
    )

    create_chat_model(settings=get_settings())

    assert _CaptureChatOllama.last_kwargs is not None
    assert _CaptureChatOllama.last_kwargs["profile"] == {
        "max_input_tokens": get_settings().llm_max_input_tokens
    }


def test_create_chat_model_uses_openai_compatible_client_for_nvidia(
    monkeypatch,
) -> None:
    _CaptureChatOpenAI.last_kwargs = None
    settings = get_settings().model_copy(update={"llm_timeout_seconds": 600.0})
    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _CaptureChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(
            lambda cls, *, settings=None: _build_snapshot(
                ModelProvider.NVIDIA, "z-ai/glm5"
            )
        ),
    )

    create_chat_model(settings=settings)

    assert _CaptureChatOpenAI.last_kwargs is not None
    assert _CaptureChatOpenAI.last_kwargs["model"] == "z-ai/glm5"
    assert _CaptureChatOpenAI.last_kwargs["api_key"] == "dummy-key"
    assert (
        _CaptureChatOpenAI.last_kwargs["base_url"]
        == "https://integrate.api.nvidia.com/v1"
    )
    assert _CaptureChatOpenAI.last_kwargs["timeout"] == 60.0
    assert _CaptureChatOpenAI.last_kwargs["max_retries"] == 0
    assert _CaptureChatOpenAI.last_kwargs["profile"] == {
        "max_input_tokens": settings.llm_max_input_tokens
    }


def test_create_chat_model_passes_nvidia_thinking_via_extra_body(monkeypatch) -> None:
    _CaptureChatOpenAI.last_kwargs = None
    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _CaptureChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(
            lambda cls, *, settings=None: _build_snapshot(
                ModelProvider.NVIDIA, "z-ai/glm5", thinking_enabled=True
            )
        ),
    )

    create_chat_model(settings=get_settings())

    assert _CaptureChatOpenAI.last_kwargs is not None
    assert _CaptureChatOpenAI.last_kwargs["use_responses_api"] is False
    assert _CaptureChatOpenAI.last_kwargs["extra_body"] == {
        "chat_template_kwargs": {
            "enable_thinking": True,
            "clear_thinking": False,
        }
    }
    assert "reasoning" not in _CaptureChatOpenAI.last_kwargs
    assert not _CaptureChatOpenAI.last_kwargs.get("use_previous_response_id", False)


def test_create_chat_model_never_enables_response_id_replay_for_nvidia(
    monkeypatch,
) -> None:
    _CaptureChatOpenAI.last_kwargs = None
    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _CaptureChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(
            lambda cls, *, settings=None: _build_snapshot(
                ModelProvider.NVIDIA, "z-ai/glm5"
            )
        ),
    )

    create_chat_model(settings=get_settings(), use_previous_response_id=True)

    assert _CaptureChatOpenAI.last_kwargs is not None
    assert _CaptureChatOpenAI.last_kwargs["use_responses_api"] is False
    assert not _CaptureChatOpenAI.last_kwargs.get("use_previous_response_id", False)


def test_create_chat_model_can_disable_nvidia_thinking(monkeypatch) -> None:
    _CaptureChatOpenAI.last_kwargs = None
    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _CaptureChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(
            lambda cls, *, settings=None: _build_snapshot(
                ModelProvider.NVIDIA, "z-ai/glm5", thinking_enabled=False
            )
        ),
    )

    create_chat_model(settings=get_settings())

    assert _CaptureChatOpenAI.last_kwargs is not None
    assert _CaptureChatOpenAI.last_kwargs["extra_body"] == {
        "chat_template_kwargs": {
            "enable_thinking": False,
            "clear_thinking": False,
        }
    }
