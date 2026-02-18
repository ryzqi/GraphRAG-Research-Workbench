from __future__ import annotations

from dataclasses import dataclass

from app.models.model_config import ModelProvider
from app.services.model_config_service import (
    _pick_next_enabled_provider,
    _provider_candidates_after,
)


@dataclass
class _ProviderRow:
    provider: ModelProvider
    enabled: bool
    model: str | None = None


def test_provider_candidates_after_wraps_in_defined_order() -> None:
    assert _provider_candidates_after(ModelProvider.OPENAI) == [
        ModelProvider.OLLAMA,
        ModelProvider.NVIDIA,
    ]
    assert _provider_candidates_after(ModelProvider.NVIDIA) == [
        ModelProvider.OPENAI,
        ModelProvider.OLLAMA,
    ]


def test_pick_next_enabled_provider_selects_first_enabled_after_current() -> None:
    rows = {
        ModelProvider.OPENAI: _ProviderRow(provider=ModelProvider.OPENAI, enabled=False),
        ModelProvider.OLLAMA: _ProviderRow(provider=ModelProvider.OLLAMA, enabled=True),
        ModelProvider.NVIDIA: _ProviderRow(provider=ModelProvider.NVIDIA, enabled=True),
    }
    selected = _pick_next_enabled_provider(
        by_provider=rows,
        current_provider=ModelProvider.OPENAI,
    )
    assert selected is not None
    assert selected.provider == ModelProvider.OLLAMA


def test_pick_next_enabled_provider_prefers_enabled_provider_with_model() -> None:
    rows = {
        ModelProvider.OPENAI: _ProviderRow(provider=ModelProvider.OPENAI, enabled=False),
        ModelProvider.OLLAMA: _ProviderRow(provider=ModelProvider.OLLAMA, enabled=True, model=None),
        ModelProvider.NVIDIA: _ProviderRow(
            provider=ModelProvider.NVIDIA,
            enabled=True,
            model="nvidia/llama-3.1-nemotron-nano-8b-v1",
        ),
    }

    selected = _pick_next_enabled_provider(
        by_provider=rows,
        current_provider=ModelProvider.OPENAI,
    )
    assert selected is not None
    assert selected.provider == ModelProvider.NVIDIA


def test_pick_next_enabled_provider_returns_none_when_no_enabled_provider() -> None:
    rows = {
        ModelProvider.OPENAI: _ProviderRow(provider=ModelProvider.OPENAI, enabled=False),
        ModelProvider.OLLAMA: _ProviderRow(provider=ModelProvider.OLLAMA, enabled=False),
        ModelProvider.NVIDIA: _ProviderRow(provider=ModelProvider.NVIDIA, enabled=False),
    }
    selected = _pick_next_enabled_provider(
        by_provider=rows,
        current_provider=ModelProvider.OPENAI,
    )
    assert selected is None
