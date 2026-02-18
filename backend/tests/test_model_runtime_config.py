from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.model_runtime_config import (
    RuntimeModelSnapshot,
    RuntimeProviderConfig,
    _resolve_active_provider,
)
from app.models.model_config import ModelProvider


def _provider_config(provider: ModelProvider, *, enabled: bool) -> RuntimeProviderConfig:
    return RuntimeProviderConfig(
        provider=provider,
        enabled=enabled,
        base_url=None,
        api_key=None,
        models=[f"{provider.value}-model"],
        thinking_enabled=True,
        thinking_level="high",
    )


def test_provider_config_keeps_models_list() -> None:
    provider = _provider_config(ModelProvider.OPENAI, enabled=True)
    assert provider.models == ["openai-model"]


def test_active_provider_config_falls_back_to_enabled_provider() -> None:
    snapshot = RuntimeModelSnapshot(
        providers={
            ModelProvider.OPENAI: _provider_config(ModelProvider.OPENAI, enabled=False),
            ModelProvider.OLLAMA: _provider_config(ModelProvider.OLLAMA, enabled=True),
            ModelProvider.NVIDIA: _provider_config(ModelProvider.NVIDIA, enabled=True),
        },
        active_provider=ModelProvider.OPENAI,
        active_model="openai-model",
        updated_at=datetime.now(timezone.utc),
    )

    active = snapshot.active_provider_config()
    assert active.provider == ModelProvider.OLLAMA
    assert active.enabled is True


def test_active_provider_config_raises_when_all_disabled() -> None:
    snapshot = RuntimeModelSnapshot(
        providers={
            ModelProvider.OPENAI: _provider_config(ModelProvider.OPENAI, enabled=False),
            ModelProvider.OLLAMA: _provider_config(ModelProvider.OLLAMA, enabled=False),
        },
        active_provider=ModelProvider.OPENAI,
        active_model="openai-model",
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(RuntimeError, match="No enabled model provider configured"):
        snapshot.active_provider_config()


def test_resolve_active_provider_prefers_requested_enabled() -> None:
    providers = {
        ModelProvider.OPENAI: _provider_config(ModelProvider.OPENAI, enabled=True),
        ModelProvider.OLLAMA: _provider_config(ModelProvider.OLLAMA, enabled=True),
    }
    active = _resolve_active_provider(
        providers=providers,
        requested_provider=ModelProvider.OPENAI,
    )
    assert active == ModelProvider.OPENAI


def test_resolve_active_provider_uses_next_enabled_when_requested_disabled() -> None:
    providers = {
        ModelProvider.OPENAI: _provider_config(ModelProvider.OPENAI, enabled=False),
        ModelProvider.OLLAMA: _provider_config(ModelProvider.OLLAMA, enabled=True),
        ModelProvider.NVIDIA: _provider_config(ModelProvider.NVIDIA, enabled=True),
    }
    active = _resolve_active_provider(
        providers=providers,
        requested_provider=ModelProvider.OPENAI,
    )
    assert active == ModelProvider.OLLAMA
