from __future__ import annotations

from types import SimpleNamespace

from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

from app.agents import general_chat_agent
from app.core.settings import Settings
from app.services import research_runtime_factory
from app.services.research_runtime_types import ResearchRuntimeConfig


class _NamedTool(SimpleNamespace):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description=f"{name} description")


def test_prompt_caching_settings_defaults_enable_anthropic_middleware() -> None:
    fields = Settings.model_fields

    assert fields["anthropic_prompt_caching_enabled"].default is True
    assert fields["anthropic_prompt_cache_ttl"].default == "5m"
    assert fields["anthropic_prompt_cache_min_messages"].default == 0


def test_general_chat_installs_anthropic_prompt_caching_middleware(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(general_chat_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        general_chat_agent.CheckpointManager,
        "get_checkpointer",
        lambda: None,
    )

    general_chat_agent.build_general_chat_agent(
        chat_model=SimpleNamespace(_llm_type="fake-chat-model"),
        tools=[],
        system_prompt="system",
        summary_trigger=("messages", 12),
        summary_keep_messages=20,
        summary_trim_tokens=4_000,
        tool_context_trigger_tokens=2_000,
        anthropic_prompt_caching_enabled=True,
        anthropic_prompt_cache_ttl="1h",
        anthropic_prompt_cache_min_messages=2,
    )

    middleware = captured["middleware"]
    caching = next(
        item
        for item in middleware
        if isinstance(item, AnthropicPromptCachingMiddleware)
    )

    assert caching.ttl == "1h"
    assert caching.min_messages_to_cache == 2
    assert caching.unsupported_model_behavior == "ignore"


def test_general_chat_skips_anthropic_prompt_caching_when_disabled(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(general_chat_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        general_chat_agent.CheckpointManager,
        "get_checkpointer",
        lambda: None,
    )

    general_chat_agent.build_general_chat_agent(
        chat_model=SimpleNamespace(_llm_type="fake-chat-model"),
        tools=[],
        system_prompt="system",
        summary_trigger=("messages", 12),
        summary_keep_messages=20,
        summary_trim_tokens=4_000,
        tool_context_trigger_tokens=2_000,
        anthropic_prompt_caching_enabled=False,
    )

    middleware = captured["middleware"]

    assert not any(
        isinstance(item, AnthropicPromptCachingMiddleware) for item in middleware
    )


def test_deep_research_installs_anthropic_prompt_caching_middleware(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_build_research_tool_registry(**_kwargs):
        return SimpleNamespace(
            tools=[_NamedTool("record_runtime_activity")],
            tool_meta_by_name={},
            tool_groups={"web": (), "paper": ()},
        )

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        research_runtime_factory,
        "build_research_tool_registry",
        fake_build_research_tool_registry,
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "create_deep_agent",
        fake_create_deep_agent,
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "_assemble_research_subagents",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "build_breadth_gate_middleware",
        lambda **_kwargs: "breadth",
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "build_agent_model_safety_middleware",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "build_tool_selector_middleware",
        lambda **_kwargs: [],
    )

    config = ResearchRuntimeConfig(
        primary_model=SimpleNamespace(),
        subagent_model=SimpleNamespace(),
        system_prompt="system",
    )

    import asyncio

    asyncio.run(
        research_runtime_factory.create_deep_research_runtime(
            settings=Settings(
                ANTHROPIC_PROMPT_CACHING_ENABLED=True,
                ANTHROPIC_PROMPT_CACHE_TTL="1h",
                ANTHROPIC_PROMPT_CACHE_MIN_MESSAGES=3,
            ),
            config=config,
        )
    )

    middleware = captured["middleware"]
    caching = next(
        item
        for item in middleware
        if isinstance(item, AnthropicPromptCachingMiddleware)
    )

    assert caching.ttl == "1h"
    assert caching.min_messages_to_cache == 3
    assert caching.unsupported_model_behavior == "ignore"
