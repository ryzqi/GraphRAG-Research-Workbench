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


class _CaptureChatNVIDIA:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def _build_snapshot(provider: ModelProvider, model: str) -> RuntimeModelSnapshot:
    return RuntimeModelSnapshot(
        providers={
            provider: RuntimeProviderConfig(
                provider=provider,
                enabled=True,
                base_url=(
                    'http://127.0.0.1:11434'
                    if provider == ModelProvider.OLLAMA
                    else 'https://integrate.api.nvidia.com/v1'
                ),
                api_key='dummy-key' if provider == ModelProvider.NVIDIA else None,
                models=[model],
                thinking_enabled=True,
                thinking_level='high' if provider == ModelProvider.OLLAMA else None,
            )
        },
        active_provider=provider,
        active_model=model,
        updated_at=datetime.now(timezone.utc),
    )


def test_create_chat_model_passes_profile_to_ollama(monkeypatch) -> None:
    fake_module = ModuleType('langchain_ollama')
    fake_module.ChatOllama = _CaptureChatOllama
    monkeypatch.setitem(sys.modules, 'langchain_ollama', fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        'get_snapshot',
        classmethod(lambda cls, *, settings=None: _build_snapshot(ModelProvider.OLLAMA, 'kimi-k2.5:cloud')),
    )

    create_chat_model(settings=get_settings())

    assert _CaptureChatOllama.last_kwargs is not None
    assert _CaptureChatOllama.last_kwargs['profile'] == {
        'max_input_tokens': get_settings().llm_max_input_tokens
    }


def test_create_chat_model_passes_profile_to_nvidia(monkeypatch) -> None:
    fake_module = ModuleType('langchain_nvidia_ai_endpoints')
    fake_module.ChatNVIDIA = _CaptureChatNVIDIA
    monkeypatch.setitem(sys.modules, 'langchain_nvidia_ai_endpoints', fake_module)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        'get_snapshot',
        classmethod(lambda cls, *, settings=None: _build_snapshot(ModelProvider.NVIDIA, 'z-ai/glm5')),
    )

    create_chat_model(settings=get_settings())

    assert _CaptureChatNVIDIA.last_kwargs is not None
    assert _CaptureChatNVIDIA.last_kwargs['profile'] == {
        'max_input_tokens': get_settings().llm_max_input_tokens
    }
