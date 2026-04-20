from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelFallbackMiddleware
from langchain.messages import AIMessage

from app.agents.kb_chat_agentic.model_guard import (
    KbChatModelCallLimitExceeded,
    guard_kb_chat_model,
)
from app.agents.model_safety import build_agent_model_safety_middleware
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_fallback_chat_model
from app.integrations.model_runtime_config import (
    RuntimeModelSnapshot,
    RuntimeProviderConfig,
)
from app.models.model_config import ModelProvider


class _FakeChatModel:
    def __init__(self, content: str = "ok", *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail

    def bind(self, **_kwargs):
        return self

    def with_structured_output(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, _messages, config=None):
        self.last_config = config
        if self.fail:
            raise RuntimeError("primary failed")
        return AIMessage(content=self.content)


def test_model_safety_settings_defaults_enable_agent_call_limits() -> None:
    fields = Settings.model_fields

    assert fields["kb_chat_run_model_call_limit"].default == 24
    assert fields["deep_research_thread_model_call_limit"].default == 240
    assert fields["deep_research_run_model_call_limit"].default == 120
    assert fields["deep_research_fallback_model_id"].default is None


def test_build_agent_model_safety_middleware_installs_call_limit_and_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.model_safety.resolve_fallback_chat_model",
        lambda **_kwargs: _FakeChatModel("fallback"),
    )

    middleware = build_agent_model_safety_middleware(
        settings=Settings(
            DEEP_RESEARCH_THREAD_MODEL_CALL_LIMIT=11,
            DEEP_RESEARCH_RUN_MODEL_CALL_LIMIT=7,
            DEEP_RESEARCH_FALLBACK_MODEL_ID="fallback-model",
        ),
        thread_limit_setting="deep_research_thread_model_call_limit",
        run_limit_setting="deep_research_run_model_call_limit",
        fallback_model_id_setting="deep_research_fallback_model_id",
        use_previous_response_id=False,
    )

    call_limit = next(
        item for item in middleware if isinstance(item, ModelCallLimitMiddleware)
    )
    fallback = next(
        item for item in middleware if isinstance(item, ModelFallbackMiddleware)
    )

    assert call_limit.thread_limit == 11
    assert call_limit.run_limit == 7
    assert call_limit.exit_behavior == "end"
    assert len(fallback.models) == 1


def test_create_fallback_chat_model_requires_provider_qualified_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.chat_model_factory.ModelRuntimeConfigManager.get_snapshot",
        lambda **_kwargs: RuntimeModelSnapshot(
            providers={
                ModelProvider.OPENAI: RuntimeProviderConfig(
                    provider=ModelProvider.OPENAI,
                    enabled=True,
                    base_url="https://openai.test/v1",
                    api_key="test-key",
                    models=["shared-model"],
                    thinking_enabled=False,
                    thinking_level=None,
                ),
                ModelProvider.ANTHROPIC: RuntimeProviderConfig(
                    provider=ModelProvider.ANTHROPIC,
                    enabled=True,
                    base_url="https://anthropic.test",
                    api_key="test-key",
                    models=["shared-model"],
                    thinking_enabled=False,
                    thinking_level=None,
                ),
            },
            active_provider=ModelProvider.OPENAI,
            active_model="shared-model",
            updated_at=None,
        ),
    )

    with pytest.raises(ValueError, match="provider:model"):
        create_fallback_chat_model(
            fallback_model_id="shared-model",
            settings=Settings(),
        )


@pytest.mark.asyncio
async def test_kb_chat_guard_enforces_run_model_call_limit() -> None:
    guarded = guard_kb_chat_model(
        _FakeChatModel("ok"),
        settings=Settings(KB_CHAT_RUN_MODEL_CALL_LIMIT=1),
    )

    first = await guarded.ainvoke([])

    assert first.content == "ok"
    with pytest.raises(KbChatModelCallLimitExceeded):
        await guarded.bind(max_tokens=8).ainvoke([])


@pytest.mark.asyncio
async def test_kb_chat_guard_uses_fallback_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.model_guard.resolve_fallback_chat_model",
        lambda **_kwargs: _FakeChatModel("fallback"),
    )

    guarded = guard_kb_chat_model(
        _FakeChatModel(fail=True),
        settings=Settings(
            KB_CHAT_RUN_MODEL_CALL_LIMIT=2,
            KB_CHAT_FALLBACK_MODEL_ID="fallback-model",
        ),
    )

    result = await guarded.with_structured_output(object).ainvoke([])

    assert result.content == "fallback"
