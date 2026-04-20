from __future__ import annotations

from types import SimpleNamespace

from langchain.agents.middleware import PIIMiddleware

from app.agents import general_chat_agent
from app.core.settings import Settings
from app.services import research_runtime_factory
from app.services.research_runtime_types import ResearchRuntimeConfig


class _NamedTool(SimpleNamespace):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description=f"{name} description")


def test_pii_settings_defaults() -> None:
    fields = Settings.model_fields

    assert fields["pii_middleware_enabled"].default is True
    assert fields["pii_redaction_strategy"].default == "redact"
    assert fields["pii_apply_to_tool_results"].default is False
    assert fields["export_redaction_enabled"].default is True


def test_general_chat_installs_pii_middleware_when_enabled(monkeypatch) -> None:
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
        tools=[_NamedTool("search")],
        system_prompt="system",
        summary_trigger=("messages", 12),
        summary_keep_messages=20,
        summary_trim_tokens=4_000,
        tool_context_trigger_tokens=2_000,
        pii_middleware_enabled=True,
        pii_redaction_strategy="mask",
        pii_apply_to_tool_results=True,
    )

    middleware = captured["middleware"]
    pii_middlewares = [
        item for item in middleware if isinstance(item, PIIMiddleware)
    ]

    assert {item.pii_type for item in pii_middlewares} >= {
        "email",
        "phone_number",
        "id_card",
    }

    email_middleware = next(
        item for item in pii_middlewares if item.pii_type == "email"
    )
    assert email_middleware.strategy == "mask"
    assert email_middleware.apply_to_input is False
    assert email_middleware.apply_to_output is True
    assert email_middleware.apply_to_tool_results is True


def test_general_chat_skips_pii_middleware_when_disabled(monkeypatch) -> None:
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
        pii_middleware_enabled=False,
    )

    middleware = captured["middleware"]
    assert not any(isinstance(item, PIIMiddleware) for item in middleware)


def test_deep_research_installs_pii_middleware(monkeypatch) -> None:
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
    monkeypatch.setattr(
        research_runtime_factory,
        "build_anthropic_prompt_caching_middleware",
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
                PII_MIDDLEWARE_ENABLED=True,
                PII_REDACTION_STRATEGY="hash",
                PII_APPLY_TO_TOOL_RESULTS=True,
            ),
            config=config,
        )
    )

    middleware = captured["middleware"]
    pii_middlewares = [
        item for item in middleware if isinstance(item, PIIMiddleware)
    ]

    assert pii_middlewares
    assert any(item.pii_type == "email" for item in pii_middlewares)
    assert all(item.apply_to_input is False for item in pii_middlewares)
    assert all(item.apply_to_output is True for item in pii_middlewares)
    assert all(item.apply_to_tool_results is True for item in pii_middlewares)
    assert all(item.strategy == "hash" for item in pii_middlewares)
