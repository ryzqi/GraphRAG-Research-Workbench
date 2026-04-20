from __future__ import annotations

from types import SimpleNamespace

from langchain.agents.middleware import LLMToolSelectorMiddleware

from app.agents import general_chat_agent
from app.core.settings import Settings
from app.services import research_runtime_factory
from app.services.research_runtime_types import ResearchRuntimeConfig


class _NamedTool(SimpleNamespace):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description=f"{name} description")


def test_tool_selector_settings_defaults() -> None:
    fields = Settings.model_fields

    assert fields["tool_selector_enabled"].default is True
    assert fields["tool_selector_trigger_tool_count"].default == 10
    assert fields["tool_selector_max_tools"].default == 5
    assert fields["tool_selector_model_id"].default is None
    assert fields["tool_selector_always_include"].default_factory() == []


def test_general_chat_installs_tool_selector_when_tool_count_exceeds_threshold(
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
        tools=[_NamedTool(f"tool_{i}") for i in range(11)],
        system_prompt="system",
        summary_trigger=("messages", 12),
        summary_keep_messages=20,
        summary_trim_tokens=4_000,
        tool_context_trigger_tokens=2_000,
        tool_selector_enabled=True,
        tool_selector_trigger_tool_count=10,
        tool_selector_max_tools=5,
        tool_selector_model=None,
        tool_selector_always_include=["tool_0"],
    )

    middleware = captured["middleware"]
    selector = next(
        item for item in middleware if isinstance(item, LLMToolSelectorMiddleware)
    )

    assert selector.max_tools == 5
    assert selector.always_include == ["tool_0"]


def test_general_chat_skips_tool_selector_below_threshold(monkeypatch) -> None:
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
        tools=[_NamedTool(f"tool_{i}") for i in range(10)],
        system_prompt="system",
        summary_trigger=("messages", 12),
        summary_keep_messages=20,
        summary_trim_tokens=4_000,
        tool_context_trigger_tokens=2_000,
        tool_selector_enabled=True,
        tool_selector_trigger_tool_count=10,
        tool_selector_max_tools=5,
        tool_selector_model=None,
        tool_selector_always_include=["tool_0"],
    )

    middleware = captured["middleware"]
    assert not any(isinstance(item, LLMToolSelectorMiddleware) for item in middleware)


def test_general_chat_passes_tool_selector_model_id_to_builder(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    selector_args: dict[str, object] = {}

    def fake_build_tool_selector_middleware(**kwargs):
        selector_args.update(kwargs)
        return []

    monkeypatch.setattr(general_chat_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        general_chat_agent,
        "build_tool_selector_middleware",
        fake_build_tool_selector_middleware,
    )
    monkeypatch.setattr(
        general_chat_agent.CheckpointManager,
        "get_checkpointer",
        lambda: None,
    )

    general_chat_agent.build_general_chat_agent(
        chat_model=SimpleNamespace(_llm_type="fake-chat-model"),
        tools=[_NamedTool(f"tool_{i}") for i in range(11)],
        system_prompt="system",
        summary_trigger=("messages", 12),
        summary_keep_messages=20,
        summary_trim_tokens=4_000,
        tool_context_trigger_tokens=2_000,
        tool_selector_enabled=True,
        tool_selector_trigger_tool_count=10,
        tool_selector_max_tools=5,
        tool_selector_model_id="openai:gpt-4o-mini",
        tool_selector_use_previous_response_id=False,
        tool_selector_model=None,
        tool_selector_always_include=["tool_0"],
    )

    assert selector_args["use_previous_response_id"] is False
    selector_settings = selector_args["settings"]
    assert isinstance(selector_settings, Settings)
    assert selector_settings.tool_selector_model_id == "openai:gpt-4o-mini"


async def _fake_build_registry(**_kwargs):
    return SimpleNamespace(
        tools=[_NamedTool(f"tool_{i}") for i in range(11)],
        tool_meta_by_name={},
        tool_groups={"web": ("tool_1",), "paper": ("tool_2",)},
    )


def test_deep_research_installs_tool_selector_and_keeps_record_runtime_activity(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_build_research_tool_registry(**_kwargs):
        return SimpleNamespace(
            tools=[_NamedTool("record_runtime_activity"), *[_NamedTool(f"tool_{i}") for i in range(10)]],
            tool_meta_by_name={},
            tool_groups={"web": ("tool_1",), "paper": ("tool_2",)},
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

    config = ResearchRuntimeConfig(
        primary_model=SimpleNamespace(),
        subagent_model=SimpleNamespace(),
        system_prompt="system",
    )

    runtime = research_runtime_factory.create_deep_research_runtime

    import asyncio

    result = asyncio.run(
        runtime(
            settings=Settings(
                TOOL_SELECTOR_ENABLED=True,
                TOOL_SELECTOR_TRIGGER_TOOL_COUNT=10,
                TOOL_SELECTOR_MAX_TOOLS=5,
                TOOL_SELECTOR_ALWAYS_INCLUDE="record_runtime_activity",
            ),
            config=config,
        )
    )

    assert result is not None
    middleware = captured["middleware"]
    selector = next(
        item for item in middleware if isinstance(item, LLMToolSelectorMiddleware)
    )

    assert selector.max_tools == 5
    assert selector.always_include == ["record_runtime_activity"]
