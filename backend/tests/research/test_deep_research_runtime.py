from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.services.deep_research_runtime as runtime_module
from app.services.deep_research_runtime import (
    build_research_backend_factory,
    build_research_run_config,
    create_deep_research_runtime,
)
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_PROVIDER_IDS,
    DEFAULT_RESEARCH_STREAM_POLICY,
    ResearchProviderId,
    ResearchRuntimeConfig,
)


def test_research_runtime_defaults_lock_single_entry_policy() -> None:
    config = ResearchRuntimeConfig(
        primary_model="gpt-5.2",
        subagent_model="gpt-5.2-mini",
        system_prompt="你是深度研究助手。",
    )

    assert config.include_mcp is False
    assert config.provider_ids == DEFAULT_RESEARCH_PROVIDER_IDS
    assert config.provider_ids == (
        ResearchProviderId.TAVILY,
        ResearchProviderId.JINA_READER,
        ResearchProviderId.SEARXNG,
        ResearchProviderId.ARXIV,
    )
    assert config.memory_paths == ("/memories/AGENTS.md",)
    assert config.skill_paths == ("/skills/",)
    assert config.tool_registry_kwargs == {
        "include_web_search": True,
        "include_web_extract": True,
        "include_web_crawl": True,
        "include_web_research": True,
        "include_mcp": False,
    }
    assert config.large_result_policy.spill_path_prefix == "/workspace/runtime-spill/"
    assert config.stream_policy.as_kwargs() == {"subgraphs": True, "version": "v2"}


def test_research_runtime_rejects_local_shell_backend() -> None:
    with pytest.raises(ValueError, match="LocalShellBackend"):
        ResearchRuntimeConfig(
            primary_model="gpt-5.2",
            subagent_model="gpt-5.2-mini",
            system_prompt="你是深度研究助手。",
            command_execution_backend="local_shell",
        )


def test_backend_factory_routes_state_and_store_paths() -> None:
    captured: dict[str, Any] = {}

    class FakeStateBackend:
        def __init__(self, runtime: object) -> None:
            self.runtime = runtime

    class FakeStoreBackend:
        def __init__(self, runtime: object) -> None:
            self.runtime = runtime

    class FakeCompositeBackend:
        def __init__(self, *, default: object, routes: dict[str, object]) -> None:
            captured["default"] = default
            captured["routes"] = routes

    original_state_backend = runtime_module.StateBackend
    original_store_backend = runtime_module.StoreBackend
    original_composite_backend = runtime_module.CompositeBackend
    runtime_module.StateBackend = FakeStateBackend  # type: ignore[assignment]
    runtime_module.StoreBackend = FakeStoreBackend  # type: ignore[assignment]
    runtime_module.CompositeBackend = FakeCompositeBackend  # type: ignore[assignment]
    try:
        factory = build_research_backend_factory()
        backend = factory("runtime-sentinel")
    finally:
        runtime_module.StateBackend = original_state_backend  # type: ignore[assignment]
        runtime_module.StoreBackend = original_store_backend  # type: ignore[assignment]
        runtime_module.CompositeBackend = original_composite_backend  # type: ignore[assignment]

    assert isinstance(backend, FakeCompositeBackend)
    assert isinstance(captured["default"], FakeStateBackend)
    assert set(captured["routes"].keys()) == {
        "/workspace/",
        "/scratch/",
        "/plans/",
        "/memories/",
        "/skills/",
    }
    assert isinstance(captured["routes"]["/workspace/"], FakeStateBackend)
    assert isinstance(captured["routes"]["/scratch/"], FakeStateBackend)
    assert isinstance(captured["routes"]["/plans/"], FakeStateBackend)
    assert isinstance(captured["routes"]["/memories/"], FakeStoreBackend)
    assert isinstance(captured["routes"]["/skills/"], FakeStoreBackend)


def test_research_run_config_uses_thread_id_and_v2_streaming_contract() -> None:
    assert build_research_run_config(thread_id="research-session-1") == {
        "configurable": {"thread_id": "research-session-1"}
    }
    assert DEFAULT_RESEARCH_STREAM_POLICY.as_kwargs() == {
        "subgraphs": True,
        "version": "v2",
    }


@pytest.mark.asyncio
async def test_create_deep_research_runtime_uses_single_deepagents_entry() -> None:
    captured: dict[str, Any] = {}
    settings_sentinel = object()
    checkpointer_sentinel = object()
    store_sentinel = object()

    async def fake_build_tool_registry(**kwargs: Any) -> tuple[list[object], dict[str, object]]:
        captured["registry_kwargs"] = kwargs
        return [SimpleNamespace(name="web_search")], {
            "web_search": SimpleNamespace(tool_name="web_search")
        }

    def fake_create_deep_agent(**kwargs: Any) -> str:
        captured["agent_kwargs"] = kwargs
        return "deep-agent-sentinel"

    original_build_tool_registry = runtime_module.build_tool_registry
    original_create_deep_agent = runtime_module.create_deep_agent
    runtime_module.build_tool_registry = fake_build_tool_registry  # type: ignore[assignment]
    runtime_module.create_deep_agent = fake_create_deep_agent  # type: ignore[assignment]
    try:
        config = ResearchRuntimeConfig(
            primary_model="gpt-5.2",
            subagent_model="gpt-5.2-mini",
            system_prompt="你是深度研究助手。",
            interrupt_on={"write_file": True},
        )
        runtime = await create_deep_research_runtime(
            settings=cast(Any, settings_sentinel),
            config=config,
            checkpointer=checkpointer_sentinel,
            store=store_sentinel,
        )
    finally:
        runtime_module.build_tool_registry = original_build_tool_registry  # type: ignore[assignment]
        runtime_module.create_deep_agent = original_create_deep_agent  # type: ignore[assignment]

    assert captured["registry_kwargs"]["settings"] is settings_sentinel
    assert captured["registry_kwargs"]["include_web_search"] is True
    assert captured["registry_kwargs"]["include_web_extract"] is True
    assert captured["registry_kwargs"]["include_web_crawl"] is True
    assert captured["registry_kwargs"]["include_web_research"] is True
    assert captured["registry_kwargs"]["include_mcp"] is False

    assert runtime.agent == "deep-agent-sentinel"
    assert runtime.tools[0].name == "web_search"
    assert captured["agent_kwargs"]["model"] == "gpt-5.2"
    assert callable(captured["agent_kwargs"]["backend"])
    assert captured["agent_kwargs"]["checkpointer"] is checkpointer_sentinel
    assert captured["agent_kwargs"]["store"] is store_sentinel
    assert captured["agent_kwargs"]["memory"] == ["/memories/AGENTS.md"]
    assert captured["agent_kwargs"]["skills"] == ["/skills/"]
    assert captured["agent_kwargs"]["interrupt_on"] == {"write_file": True}
    assert captured["agent_kwargs"]["subagents"] == [
        {
            "name": "general-purpose",
            "description": "通用深度研究子代理，负责隔离多步资料搜集与综合。",
            "system_prompt": "你是深度研究助手。",
            "tools": runtime.tools,
            "model": "gpt-5.2-mini",
            "skills": ["/skills/"],
            "interrupt_on": {"write_file": True},
        }
    ]
    assert runtime.make_run_config(thread_id="research-thread-1") == {
        "configurable": {"thread_id": "research-thread-1"}
    }
    assert runtime.stream_kwargs() == {"subgraphs": True, "version": "v2"}
