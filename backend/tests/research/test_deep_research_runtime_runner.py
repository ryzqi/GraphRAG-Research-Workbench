from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.research_artifact import ResearchArtifact
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
from app.services.research_runtime_types import (
    ResearchLargeResultPolicy,
    ResearchRuntimeConfig,
)
from app.services.research_workspace_files import build_workspace_bootstrap_artifact_path_map


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
    session.artifacts = []
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
    assert result.source_bundle.coverage_gaps == []
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
    assert request["files"]["/workspace/context/query_mesh.json"]["content"]
    query_mesh_payload = json.loads(
        "\n".join(request["files"]["/workspace/context/query_mesh.json"]["content"])
    )
    assert query_mesh_payload["canonical_query"] == "概述当前 Deep Research session contract"
    assert query_mesh_payload["verification_queries"]
    assert "/workspace/context/kb_context.md" not in request["files"]
    assert "source_type=kb" not in request["messages"][0]["content"]
    assert "/workspace/context/query_mesh.json" in request["messages"][0]["content"]
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
    session.artifacts = []
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
async def test_deep_research_runtime_runner_enforces_required_web_provider_gaps_for_comparative_plan() -> None:
    agent = _FakeAgent(
        {
            "structured_response": {
                "findings": [
                    "Tavily 负责广度召回。",
                    "Jina Reader 负责正文读取。",
                ],
                "citations": [
                    {
                        "source_type": "web",
                        "source_provider": "tavily",
                        "retrieval_method": "search",
                        "source_id": "https://example.com/tavily",
                        "title": "Tavily Result",
                        "url": "https://example.com/tavily",
                        "origin_url": "https://example.com/tavily",
                    },
                    {
                        "source_type": "web",
                        "source_provider": "jina_reader",
                        "retrieval_method": "read",
                        "source_id": "https://r.jina.ai/http://example.com/jina",
                        "title": "Jina Result",
                        "url": "https://r.jina.ai/http://example.com/jina",
                        "origin_url": "https://example.com/jina",
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
        tool_groups={
            "web": ("tavily_search", "jina_read", "searxng_search"),
            "web_provider_ids": ("tavily", "jina_reader", "searxng"),
            "paper": (),
            "citation": (),
        },
    )
    runner = DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files={"/workspace/context/api_contract_research.md": "# api contract"},
    )
    session_id = uuid.uuid4()
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="对比多个 deep research provider 的证据覆盖",
    )
    session.artifacts = []
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="比较多 provider 的 deep research evidence coverage。",
        complexity="comparative",
        summary="比较 Tavily、Jina Reader 与 SearXNG 的互补性。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="对比 provider coverage",
                description="验证 comparative 计划要求至少 3 个 web providers。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )

    result = await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    assert result.source_bundle.coverage_gaps == ["缺少 provider 证据：searxng"]


@pytest.mark.asyncio
async def test_deep_research_runtime_runner_skips_web_provider_requirements_for_paper_only_plan() -> None:
    agent = _FakeAgent(
        {
            "structured_response": {
                "findings": [
                    "Paper A 提供研究基线。",
                    "Paper B 提供补充论据。",
                ],
                "citations": [
                    {
                        "source_type": "paper",
                        "source_provider": "arxiv",
                        "retrieval_method": "fetch",
                        "source_id": "arxiv:2501.00001",
                        "title": "Paper A",
                        "url": "https://arxiv.org/abs/2501.00001",
                        "origin_url": "https://arxiv.org/abs/2501.00001",
                        "arxiv_id": "2501.00001",
                        "pdf_url": "https://arxiv.org/pdf/2501.00001.pdf",
                    },
                    {
                        "source_type": "paper",
                        "source_provider": "arxiv",
                        "retrieval_method": "fetch",
                        "source_id": "arxiv:2501.00002",
                        "title": "Paper B",
                        "url": "https://arxiv.org/abs/2501.00002",
                        "origin_url": "https://arxiv.org/abs/2501.00002",
                        "arxiv_id": "2501.00002",
                        "pdf_url": "https://arxiv.org/pdf/2501.00002.pdf",
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
        tool_groups={
            "web": ("tavily_search", "jina_read", "searxng_search"),
            "web_provider_ids": ("tavily", "jina_reader", "searxng"),
            "paper": ("arxiv_search", "arxiv_fetch"),
            "citation": (),
        },
    )
    runner = DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files={"/workspace/context/api_contract_research.md": "# api contract"},
    )
    session_id = uuid.uuid4()
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="整理论文研究基线",
    )
    session.artifacts = []
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="只基于论文做研究。",
        complexity="complex",
        summary="paper-only 不应要求 web provider。",
        target_sources=[ResearchSourceTarget.PAPER],
    )

    result = await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    assert result.source_bundle.coverage_gaps == []


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
    session_id = uuid.uuid4()
    workspace_path_map = build_workspace_bootstrap_artifact_path_map(session_id=session_id)
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
                        "source_id": workspace_path_map["mission_md"],
                        "title": "00-mission.md",
                        "url": f"file://{workspace_path_map['mission_md']}",
                        "origin_url": f"file://{workspace_path_map['mission_md']}",
                    },
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": workspace_path_map["plan_md"],
                        "title": "01-plan.md",
                        "url": f"file://{workspace_path_map['plan_md']}",
                        "origin_url": f"file://{workspace_path_map['plan_md']}",
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
        workspace_files={"/workspace/context/api_contract_research.md": "# api contract"},
    )
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="把 workspace bootstrap 注入 runtime request",
    )
    session.artifacts = [
        ResearchArtifact(
            artifact_key="mission_md",
            content_text="# Mission",
        ),
        ResearchArtifact(
            artifact_key="plan_md",
            content_text="# Plan",
        ),
    ]
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
    assert workspace_path_map["mission_md"] in request["files"]
    assert workspace_path_map["plan_md"] in request["files"]
    assert request["files"][workspace_path_map["mission_md"]]["content"] == ["# Mission"]
    assert request["files"][workspace_path_map["plan_md"]]["content"] == ["# Plan"]


@pytest.mark.asyncio
async def test_runner_spills_oversized_bootstrap_artifact_using_large_result_policy() -> None:
    session_id = uuid.uuid4()
    workspace_path_map = build_workspace_bootstrap_artifact_path_map(session_id=session_id)
    oversized_mission = "# Mission\n\n" + ("A" * 80)
    spill_prefix = "/scratch/custom-runtime-spill/"
    agent = _FakeAgent(
        {
            "structured_response": {
                "findings": [
                    "超长 Mission bootstrap 会被溢写到 spill 文件。",
                    "workspace stub 会保留 spill 文件位置供代理继续读取。",
                ],
                "citations": [
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": workspace_path_map["mission_md"],
                        "title": "00-mission.md",
                        "url": f"file://{workspace_path_map['mission_md']}",
                        "origin_url": f"file://{workspace_path_map['mission_md']}",
                    },
                    {
                        "source_type": "web",
                        "source_provider": "workspace",
                        "retrieval_method": "read_file",
                        "source_id": "/workspace/context/api_contract_research.md",
                        "title": "api_contract_research.md",
                        "url": "file:///workspace/context/api_contract_research.md",
                        "origin_url": "file:///workspace/context/api_contract_research.md",
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
            large_result_policy=ResearchLargeResultPolicy(
                spill_path_prefix=spill_prefix,
                max_inline_chars=20,
            ),
        ),
        tools=[],
        tool_meta_by_name={},
        tool_groups={"web": (), "paper": (), "citation": ()},
    )
    runner = DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files={"/workspace/context/api_contract_research.md": "# api contract"},
    )
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="验证 oversized bootstrap spill",
    )
    session.artifacts = [
        ResearchArtifact(
            artifact_key="mission_md",
            content_text=oversized_mission,
        )
    ]
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="验证 oversized bootstrap 会按 policy 溢写。",
        complexity="simple",
        summary="读取 spill summary/raw 文件并保留 workspace stub。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="读取 Mission spill",
                description="确认 request.files 中出现 workspace stub 与 spill files。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )

    await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    request, _ = agent.calls[0]
    spill_base = f"{spill_prefix.rstrip('/')}/{session_id}/workspace-bootstrap/00-mission"
    summary_path = f"{spill_base}.summary.md"
    raw_path = f"{spill_base}.raw.json"
    assert workspace_path_map["mission_md"] in request["files"]
    assert summary_path in request["files"]
    assert raw_path in request["files"]
    stub_content = "\n".join(request["files"][workspace_path_map["mission_md"]]["content"])
    assert summary_path in stub_content
    assert raw_path in stub_content
    assert '"artifact_key": "mission_md"' in "\n".join(request["files"][raw_path]["content"])


@pytest.mark.asyncio
async def test_runner_requires_preloaded_session_artifacts() -> None:
    agent = _FakeAgent(
        {
            "structured_response": {
                "findings": ["a", "b"],
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
        workspace_files={"/workspace/context/api_contract_research.md": "# api contract"},
    )
    session_id = uuid.uuid4()
    session = ResearchSession(
        id=session_id,
        thread_id=str(session_id),
        question="验证 artifacts 预加载契约",
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="未预加载 artifacts 时应 fail fast。",
        complexity="simple",
        summary="阻止 runtime 静默吞掉 bootstrap files。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="检查 preloaded artifacts",
                description="如果 session.artifacts 未预加载，应立即报错。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )

    with pytest.raises(RuntimeError, match="artifacts.*preload"):
        await runner.run_session(session=session, plan_snapshot=plan_snapshot)

    assert agent.calls == []
