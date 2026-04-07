from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from app.integrations.model_health_probe import _has_probe_content, probe_runtime_target
from app.integrations.model_runtime_config import RuntimeProviderConfig
from app.models.model_config import ModelProvider


def test_has_probe_content_accepts_plain_text_response() -> None:
    response = AIMessage(content="OK")

    assert _has_probe_content(response) is True


def test_has_probe_content_accepts_reasoning_only_response() -> None:
    response = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "模型已完成推理"},
    )

    assert _has_probe_content(response) is True


@pytest.mark.asyncio
async def test_probe_runtime_target_accepts_reasoning_only_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeChatModel:
        async def ainvoke(self, _messages: list[object]) -> AIMessage:
            return AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "模型已完成推理"},
            )

    monkeypatch.setattr(
        "app.integrations.model_health_probe.create_chat_model_from_runtime_config",
        lambda **_kwargs: _FakeChatModel(),
    )

    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.OLLAMA,
        enabled=True,
        base_url="http://127.0.0.1:11434",
        api_key=None,
        models=["reasoner:latest"],
        thinking_enabled=True,
        thinking_level="high",
    )

    await probe_runtime_target(provider_cfg=provider_cfg, model_name="reasoner:latest")
