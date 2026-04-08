from __future__ import annotations

from typing import Any

import pytest
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from app.services.deep_research_runtime import create_deep_research_runtime
from app.services.research_runtime_types import ResearchRuntimeConfig, ResearchToolRegistryBundle


@pytest.mark.asyncio
async def test_create_deep_research_runtime_passes_backend_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    async def fake_build_research_tool_registry(**_: Any) -> ResearchToolRegistryBundle:
        return ResearchToolRegistryBundle(
            tools=[],
            tool_meta_by_name={},
            tool_groups={},
        )

    def fake_create_deep_agent(**kwargs: Any) -> object:
        captured_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(
        "app.services.deep_research_runtime.build_research_tool_registry",
        fake_build_research_tool_registry,
    )
    monkeypatch.setattr(
        "app.services.deep_research_runtime.create_deep_agent",
        fake_create_deep_agent,
    )

    config = ResearchRuntimeConfig(
        primary_model="primary-model",
        subagent_model="subagent-model",
        finalizer_model="finalizer-model",
        system_prompt="system prompt",
    )

    await create_deep_research_runtime(
        settings=object(),
        config=config,
        checkpointer=object(),
        store=object(),
    )

    backend = captured_kwargs["backend"]
    assert isinstance(backend, CompositeBackend)
    assert not callable(backend)
    assert isinstance(backend.default, StateBackend)
    assert set(backend.routes) == {
        "/workspace/",
        "/scratch/",
        "/plans/",
        "/memories/",
        "/skills/",
    }
    assert isinstance(backend.routes["/workspace/"], StateBackend)
    assert isinstance(backend.routes["/scratch/"], StateBackend)
    assert isinstance(backend.routes["/plans/"], StateBackend)
    assert isinstance(backend.routes["/memories/"], StoreBackend)
    assert isinstance(backend.routes["/skills/"], StoreBackend)
