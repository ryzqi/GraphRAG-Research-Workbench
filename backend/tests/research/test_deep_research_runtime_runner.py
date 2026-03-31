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
    DeepResearchStructuredResponseDraft,
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
    assert "/workspace/context/kb_context.md" not in request["files"]
    assert "source_type=kb" not in request["messages"][0]["content"]
    assert config == {"configurable": {"thread_id": str(session_id)}}


@pytest.mark.asyncio
async def test_deep_research_runtime_runner_fills_missing_origin_url_for_web_citations() -> None:
    agent = _FakeAgent(
        {
            "structured_response": DeepResearchStructuredResponseDraft.model_validate(
                {
                    "findings": [
                        "workspace 文档足以回答当前问题。",
                        "缺失 origin_url 的 web citation 会在 runtime 侧补齐。",
                    ],
                    "citations": [
                        {
                            "source_type": "web",
                            "source_provider": "workspace",
                            "retrieval_method": "read_file",
                            "source_id": "/workspace/context/api_contract_research.md",
                            "title": "api_contract_research.md",
                            "url": "file:///workspace/context/api_contract_research.md",
                        },
                        {
                            "source_type": "web",
                            "source_provider": "workspace",
                            "retrieval_method": "read_file",
                            "source_id": "/workspace/context/research_readme.md",
                            "title": "research_readme.md",
                            "url": "file:///workspace/context/research_readme.md",
                        },
                    ],
                }
            )
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
            "/workspace/context/research_readme.md": "# readme",
        },
    )
    session_id = uuid.uuid4()
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="当前 deep research contract 是什么？",
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="读取 workspace 文档并生成最终研究结果。",
        complexity="simple",
        summary="以 workspace 文档为主收口 findings/citations。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="读取 workspace 文档",
                description="围绕 contract 整理最小可验证证据。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )

    result = await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    assert [citation.origin_url for citation in result.source_bundle.citations] == [
        "file:///workspace/context/api_contract_research.md",
        "file:///workspace/context/research_readme.md",
    ]


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
    response_format = captured["runtime_kwargs"]["response_format"]
    relaxed = response_format.model_validate(
        {
            "findings": [
                "web citation 即使缺少 origin_url，也应该先允许进入 runtime 归一化。",
                "runtime 后置校验会再补齐并收敛到严格契约。",
            ],
            "citations": [
                {
                    "source_type": "web",
                    "source_provider": "workspace",
                    "retrieval_method": "read_file",
                    "source_id": "/workspace/context/api_contract_research.md",
                    "title": "api_contract_research.md",
                    "url": "file:///workspace/context/api_contract_research.md",
                },
                {
                    "source_type": "web",
                    "source_provider": "workspace",
                    "retrieval_method": "read_file",
                    "source_id": "/workspace/context/design.md",
                    "title": "design.md",
                    "url": "file:///workspace/context/design.md",
                },
            ],
        }
    )
    assert len(relaxed.citations) == 2


@pytest.mark.asyncio
async def test_runner_includes_workspace_bootstrap_files_in_agent_request() -> None:
    agent = _FakeAgent(
        {
            "structured_response": {
                "findings": [
                    "Mission 与 Plan 文件应随 runtime request 一起发送。",
                    "workspace bootstrap 文件要优先于外部检索被代理读取。",
                ],
                "citations": [
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": "/workspace/research/session-1/00-mission.md",
                        "title": "00-mission.md",
                        "url": "file:///workspace/research/session-1/00-mission.md",
                        "origin_url": "file:///workspace/research/session-1/00-mission.md",
                    },
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": "/workspace/research/session-1/01-plan.md",
                        "title": "01-plan.md",
                        "url": "file:///workspace/research/session-1/01-plan.md",
                        "origin_url": "file:///workspace/research/session-1/01-plan.md",
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
            "/workspace/research/session-1/00-mission.md": "# Mission",
            "/workspace/research/session-1/01-plan.md": "# Plan",
        },
    )
    session_id = uuid.uuid4()
    session = ResearchSession(
        id=session_id,
        thread_id="session-1",
        question="把 workspace bootstrap 注入 runtime request",
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="验证 mission/plan 文件会进入 runtime request。",
        complexity="simple",
        summary="读取 workspace bootstrap 文件并生成结构化结果。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="读取 Mission 与 Plan",
                description="确认 request.files 包含 bootstrap markdown。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )

    await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    request, _ = agent.calls[0]
    assert "/workspace/research/session-1/00-mission.md" in request["files"]
    assert "/workspace/research/session-1/01-plan.md" in request["files"]
