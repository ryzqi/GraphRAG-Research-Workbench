from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.research_session import ResearchSession
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.deep_research_runtime import (
    DeepResearchRuntime,
    DeepResearchRuntimeRunner,
    build_deep_research_runtime_runner,
)
from app.services.research_runtime_types import ResearchRuntimeConfig


class _FakeAgent:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def ainvoke(self, request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((request, config))
        return dict(self._result)


@pytest.mark.asyncio
async def test_deep_research_runtime_runner_builds_source_bundle_from_structured_output() -> None:
    agent = _FakeAgent(
        {
            "structured_response": {
                "findings": [
                    "当前 session contract 以 /api/v1/research/sessions 为入口。",
                    "metrics_snapshot / gate_snapshot 会在 final 后持久化为 artifacts。",
                ],
                "citations": [
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": "/workspace/context/api_contract_research.md",
                        "title": "api_contract_research.md",
                        "url": "file:///workspace/context/api_contract_research.md",
                        "origin_url": "file:///workspace/context/api_contract_research.md",
                    },
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": "/workspace/context/design.md",
                        "title": "design.md",
                        "url": "file:///workspace/context/design.md",
                        "origin_url": "file:///workspace/context/design.md",
                    },
                ],
            }
        }
    )
    runtime = DeepResearchRuntime(
        agent=agent,
        config=ResearchRuntimeConfig(
            primary_model="gpt-5.2",
            subagent_model="gpt-5.2-mini",
            system_prompt="你是深度研究助手。",
        ),
        tools=[],
        tool_meta_by_name={},
        tool_groups={"web": (), "paper": (), "citation": ()},
    )
    runner = DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files={
            "/workspace/context/api_contract_research.md": "# api contract",
            "/workspace/context/design.md": "# design",
        },
    )
    session_id = uuid.uuid4()
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="概述当前 Deep Research session contract",
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="围绕 session contract 生成最终研究结果。",
        complexity="simple",
        summary="读取 workspace 文档并收口 findings/citations。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="读取 contract",
                description="读取 workspace 文档并总结 contract。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
        confirmation_required=False,
    )

    result = await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    assert result.latency_ms is not None
    assert result.source_bundle.findings == [
        "当前 session contract 以 /api/v1/research/sessions 为入口。",
        "metrics_snapshot / gate_snapshot 会在 final 后持久化为 artifacts。",
    ]
    assert len(result.source_bundle.citations) == 2
    assert result.source_bundle.citations[0] == ResearchCanonicalCitation(
        source_type=ResearchSourceType.WEB,
        source_provider="workspace",
        retrieval_method="read_file",
        source_id="/workspace/context/api_contract_research.md",
        title="api_contract_research.md",
        url="file:///workspace/context/api_contract_research.md",
        origin_url="file:///workspace/context/api_contract_research.md",
    )
    request, config = agent.calls[0]
    assert request["files"]["/workspace/context/api_contract_research.md"]["content"] == [
        "# api contract"
    ]
    assert request["files"]["/workspace/context/plan_snapshot.json"]["content"]
    assert config == {"configurable": {"thread_id": str(session_id)}}


@pytest.mark.asyncio
async def test_build_deep_research_runtime_runner_disables_previous_response_id_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_chat_model_calls: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}

    def _fake_create_chat_model(**kwargs: Any) -> str:
        create_chat_model_calls.append(dict(kwargs))
        return f"model-{len(create_chat_model_calls)}"

    async def _fake_create_deep_research_runtime(**kwargs: Any) -> DeepResearchRuntime:
        captured["runtime_kwargs"] = kwargs
        return DeepResearchRuntime(
            agent=_FakeAgent({"structured_response": {"findings": ["a", "b"], "citations": [
                {
                    "source_type": "web",
                    "source_provider": "workspace",
                    "retrieval_method": "read_file",
                    "source_id": "/workspace/context/api_contract_research.md",
                    "title": "api_contract_research.md",
                    "url": "file:///workspace/context/api_contract_research.md",
                    "origin_url": "file:///workspace/context/api_contract_research.md",
                },
                {
                    "source_type": "web",
                    "source_provider": "workspace",
                    "retrieval_method": "read_file",
                    "source_id": "/workspace/context/design.md",
                    "title": "design.md",
                    "url": "file:///workspace/context/design.md",
                    "origin_url": "file:///workspace/context/design.md",
                },
            ]}}),
            config=kwargs["config"],
            tools=[],
            tool_meta_by_name={},
            tool_groups={},
        )

    monkeypatch.setattr(
        "app.services.deep_research_runtime.create_chat_model",
        _fake_create_chat_model,
    )
    monkeypatch.setattr(
        "app.services.deep_research_runtime.create_deep_research_runtime",
        _fake_create_deep_research_runtime,
    )

    runner = await build_deep_research_runtime_runner(settings=SimpleNamespace())

    assert isinstance(runner, DeepResearchRuntimeRunner)
    assert len(create_chat_model_calls) == 3
    assert all(call.get("use_previous_response_id") is False for call in create_chat_model_calls)
