from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model_from_runtime_config
from app.integrations.model_runtime_config import RuntimeProviderConfig
from app.models.model_config import ModelProvider


def test_create_chat_model_from_runtime_config_does_not_set_timeout_for_openai_when_explicit_none(
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.OPENAI,
        enabled=True,
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        models=["gpt-4.1"],
        thinking_enabled=False,
        thinking_level="high",
    )

    create_chat_model_from_runtime_config(
        provider_cfg=provider_cfg,
        model_name="gpt-4.1",
        settings=Settings(),
        timeout_seconds=None,
    )

    assert "timeout" not in captured_kwargs


def test_create_chat_model_from_runtime_config_does_not_set_timeout_for_nvidia_when_explicit_none(
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.NVIDIA,
        enabled=True,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="test-key",
        models=["llama-3.1-nemotron-ultra-253b-v1"],
        thinking_enabled=True,
        thinking_level=None,
    )

    create_chat_model_from_runtime_config(
        provider_cfg=provider_cfg,
        model_name="llama-3.1-nemotron-ultra-253b-v1",
        settings=Settings(),
        timeout_seconds=None,
    )

    assert "timeout" not in captured_kwargs
