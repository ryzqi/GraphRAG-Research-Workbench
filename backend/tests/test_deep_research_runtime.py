from __future__ import annotations

from types import SimpleNamespace

from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
)
from app.prompts import get_prompt_loader
from app.services.deep_research_runtime import (
    DeepResearchRuntimeRunner,
    _build_runtime_prompt,
)
from app.services.research_runtime_context import build_runtime_context_snapshot
from app.services.research_runtime_skills import build_research_runtime_skill_files
from app.services.research_runtime_types import ResearchRuntimeConfig
from app.services.research_workspace_files import build_research_workspace_layout


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="验证 runtime skills",
        complexity=ResearchComplexity.SIMPLE,
        summary="确保运行时技能文件会注入到 deep research 请求",
        subtasks=[],
        target_sources=[ResearchSourceTarget.WEB],
    )


def test_research_runtime_config_defaults_enable_skills_but_not_memory() -> None:
    fake_model = object()
    config = ResearchRuntimeConfig(
        primary_model=fake_model,
        subagent_model=fake_model,
        finalizer_model=fake_model,
        system_prompt="runtime prompt",
    )

    assert config.skill_paths == ("/skills/",)
    assert config.memory_paths == ()


def test_build_research_runtime_skill_files_returns_runtime_and_reporting_skill() -> None:
    files = build_research_runtime_skill_files()

    assert "/skills/research-runtime/SKILL.md" in files
    assert "/skills/research-reporting/SKILL.md" in files
    assert "write_todos" in files["/skills/research-runtime/SKILL.md"]
    assert "report-context.json" in files["/skills/research-reporting/SKILL.md"]


def test_build_runtime_context_snapshot_harvests_only_whitelisted_files() -> None:
    layout = build_research_workspace_layout("session-123")
    result = {
        "files": {
            layout.claim_map_md_path: {"value": {"text": "# 核心主张\n- claim-a"}},
            layout.evidence_ledger_md_path: {
                "value": {"text": "# 证据账本\n- item-1"}
            },
            layout.analysis_notes_path: {"value": {"text": "# 中间分析\n- note"}},
            layout.report_outline_path: {"value": {"text": "# 报告提纲\n- sec"}},
            layout.report_context_json_path: {
                "value": {"text": '{"executive_summary": "summary"}'}
            },
            "/scratch/research/session-123/tmp/noise.txt": {
                "value": {"text": "ignore me"}
            },
        }
    }

    snapshot = build_runtime_context_snapshot(result=result, layout=layout)

    assert snapshot is not None
    assert snapshot.claim_map_md.startswith("# 核心主张")
    assert snapshot.report_context_json["executive_summary"] == "summary"
    assert "/scratch/research/session-123/tmp/noise.txt" not in snapshot.files_snapshot


def test_runtime_system_prompt_uses_explicit_xml_sections() -> None:
    prompt = get_prompt_loader().render_with_few_shot("research/runtime_system")

    assert "<instructions>" in prompt
    assert "<citation_policy>" in prompt


def test_runtime_user_prompt_places_static_rules_before_dynamic_task_block() -> None:
    prompt = _build_runtime_prompt(
        session=SimpleNamespace(question="What changed in HBM supply constraints?"),
        plan_snapshot=_build_plan_snapshot(),
        workspace_paths=("/workspace/context/runtime_context_guide.md",),
    )

    assert "<instructions>" in prompt
    assert "<task_context>" in prompt
    assert prompt.index("<instructions>") < prompt.index("<task_context>")
    assert prompt.index("What changed in HBM supply constraints?") > prompt.index(
        "<task_context>"
    )


async def test_runner_injects_runtime_skill_files_into_request() -> None:
    captured: dict[str, object] = {}

    class _FakeAgent:
        async def ainvoke(self, request, config, **kwargs):  # type: ignore[no-untyped-def]
            captured["request"] = request
            captured["config"] = config
            return {
                "structured_response": {
                    "findings": ["发现 A", "发现 B"],
                    "citations": [
                        {
                            "source_type": "web",
                            "source_provider": "tavily",
                            "retrieval_method": "search",
                            "source_id": "src-tavily",
                            "title": "来源 A",
                            "url": "https://example.com/a",
                            "origin_url": "https://example.com/a",
                        },
                        {
                            "source_type": "web",
                            "source_provider": "searxng",
                            "retrieval_method": "search",
                            "source_id": "src-searxng",
                            "title": "来源 B",
                            "url": "https://example.com/b",
                            "origin_url": "https://example.com/b",
                        },
                    ],
                }
            }

    fake_model = object()
    runtime = SimpleNamespace(
        agent=_FakeAgent(),
        config=ResearchRuntimeConfig(
            primary_model=fake_model,
            subagent_model=fake_model,
            finalizer_model=fake_model,
            system_prompt="runtime prompt",
        ),
        tool_groups={"web_provider_ids": ("tavily", "searxng")},
        tools=[],
        make_run_config=lambda *, thread_id: {"configurable": {"thread_id": thread_id}},
    )
    runner = DeepResearchRuntimeRunner(runtime=runtime, workspace_files={})
    session = SimpleNamespace(
        id="session-123",
        thread_id="thread-123",
        question="验证运行时技能文件是否注入",
        artifacts=[],
    )

    await runner.run_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    request = captured["request"]
    assert isinstance(request, dict)
    request_files = request["files"]
    assert isinstance(request_files, dict)
    assert "/skills/research-runtime/SKILL.md" in request_files
    assert "/skills/research-reporting/SKILL.md" in request_files


async def test_runner_returns_runtime_context_snapshot_from_result_files() -> None:
    class _FakeAgent:
        async def ainvoke(self, request, config, **kwargs):  # type: ignore[no-untyped-def]
            layout = build_research_workspace_layout("session-123")
            return {
                "structured_response": {
                    "findings": ["发现 A", "发现 B"],
                    "citations": [
                        {
                            "source_type": "web",
                            "source_provider": "tavily",
                            "retrieval_method": "search",
                            "source_id": "src-tavily",
                            "title": "来源 A",
                            "url": "https://example.com/a",
                            "origin_url": "https://example.com/a",
                        },
                        {
                            "source_type": "web",
                            "source_provider": "searxng",
                            "retrieval_method": "search",
                            "source_id": "src-searxng",
                            "title": "来源 B",
                            "url": "https://example.com/b",
                            "origin_url": "https://example.com/b",
                        },
                    ],
                },
                "files": {
                    layout.claim_map_md_path: {"value": {"text": "# 核心主张\n- claim-a"}},
                    layout.evidence_ledger_md_path: {
                        "value": {"text": "# 证据账本\n- item-1"}
                    },
                    layout.analysis_notes_path: {
                        "value": {"text": "# 中间分析\n- note"}
                    },
                    layout.report_outline_path: {"value": {"text": "# 报告提纲\n- sec"}},
                    layout.report_context_json_path: {
                        "value": {"text": '{"executive_summary": "summary"}'}
                    },
                },
            }

    fake_model = object()
    runtime = SimpleNamespace(
        agent=_FakeAgent(),
        config=ResearchRuntimeConfig(
            primary_model=fake_model,
            subagent_model=fake_model,
            finalizer_model=fake_model,
            system_prompt="runtime prompt",
        ),
        tool_groups={"web_provider_ids": ("tavily", "searxng")},
        tools=[],
        make_run_config=lambda *, thread_id: {"configurable": {"thread_id": thread_id}},
    )
    runner = DeepResearchRuntimeRunner(runtime=runtime, workspace_files={})
    session = SimpleNamespace(
        id="session-123",
        thread_id="thread-123",
        question="验证 runtime 文件回收",
        artifacts=[],
    )

    run_result = await runner.run_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    assert run_result.runtime_context_snapshot is not None
    assert run_result.runtime_context_snapshot.claim_map_md.startswith("# 核心主张")
async def test_runner_injects_runtime_context_guide_file() -> None:
    captured: dict[str, object] = {}

    class _FakeAgent:
        async def ainvoke(self, request, config, **kwargs):  # type: ignore[no-untyped-def]
            captured["request"] = request
            return {
                "structured_response": {
                    "findings": ["finding A", "finding B"],
                    "citations": [
                        {
                            "source_type": "web",
                            "source_provider": "tavily",
                            "retrieval_method": "search",
                            "source_id": "src-tavily",
                            "title": "Source A",
                            "url": "https://example.com/a",
                            "origin_url": "https://example.com/a",
                        },
                        {
                            "source_type": "web",
                            "source_provider": "searxng",
                            "retrieval_method": "search",
                            "source_id": "src-searxng",
                            "title": "Source B",
                            "url": "https://example.com/b",
                            "origin_url": "https://example.com/b",
                        },
                    ],
                }
            }

    fake_model = object()
    runtime = SimpleNamespace(
        agent=_FakeAgent(),
        config=ResearchRuntimeConfig(
            primary_model=fake_model,
            subagent_model=fake_model,
            finalizer_model=fake_model,
            system_prompt="runtime prompt",
        ),
        tool_groups={"web_provider_ids": ("tavily", "searxng")},
        tools=[],
        make_run_config=lambda *, thread_id: {"configurable": {"thread_id": thread_id}},
    )
    runner = DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files={
            "/workspace/context/api_contract_research.md": "# API Contract",
            "/scratch/research/session-123/raw/noise.json": '{"noise": true}',
        },
    )
    session = SimpleNamespace(
        id="session-123",
        thread_id="thread-123",
        question="How should the runtime manage context layers?",
        artifacts=[],
    )

    await runner.run_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    request = captured["request"]
    assert isinstance(request, dict)
    request_files = request["files"]
    assert isinstance(request_files, dict)
    assert "/workspace/context/runtime_context_guide.md" in request_files


async def test_runner_prompt_lists_only_priority_context_files() -> None:
    captured: dict[str, object] = {}

    class _FakeAgent:
        async def ainvoke(self, request, config, **kwargs):  # type: ignore[no-untyped-def]
            captured["request"] = request
            return {
                "structured_response": {
                    "findings": ["finding A", "finding B"],
                    "citations": [
                        {
                            "source_type": "web",
                            "source_provider": "tavily",
                            "retrieval_method": "search",
                            "source_id": "src-tavily",
                            "title": "Source A",
                            "url": "https://example.com/a",
                            "origin_url": "https://example.com/a",
                        },
                        {
                            "source_type": "web",
                            "source_provider": "searxng",
                            "retrieval_method": "search",
                            "source_id": "src-searxng",
                            "title": "Source B",
                            "url": "https://example.com/b",
                            "origin_url": "https://example.com/b",
                        },
                    ],
                }
            }

    fake_model = object()
    runtime = SimpleNamespace(
        agent=_FakeAgent(),
        config=ResearchRuntimeConfig(
            primary_model=fake_model,
            subagent_model=fake_model,
            finalizer_model=fake_model,
            system_prompt="runtime prompt",
        ),
        tool_groups={"web_provider_ids": ("tavily", "searxng")},
        tools=[],
        make_run_config=lambda *, thread_id: {"configurable": {"thread_id": thread_id}},
    )
    runner = DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files={
            "/workspace/context/api_contract_research.md": "# API Contract",
            "/scratch/research/session-123/raw/noise.json": '{"noise": true}',
        },
    )
    session = SimpleNamespace(
        id="session-123",
        thread_id="thread-123",
        question="How should the runtime manage context layers?",
        artifacts=[],
    )

    await runner.run_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    request = captured["request"]
    assert isinstance(request, dict)
    messages = request["messages"]
    assert isinstance(messages, list)
    prompt = messages[0]["content"]

    assert "/workspace/context/runtime_context_guide.md" in prompt
    assert "/workspace/context/api_contract_research.md" in prompt
    assert "/skills/research-runtime/SKILL.md" not in prompt
    assert "/skills/research-reporting/SKILL.md" not in prompt
    assert "/scratch/research/session-123/raw/noise.json" not in prompt


async def test_runner_passes_runtime_context_to_agent_invoke() -> None:
    captured: dict[str, object] = {}

    class _FakeAgent:
        async def ainvoke(self, request, config, **kwargs):  # type: ignore[no-untyped-def]
            captured["request"] = request
            captured["config"] = config
            captured["context"] = kwargs.get("context")
            return {
                "structured_response": {
                    "findings": ["finding A", "finding B"],
                    "citations": [
                        {
                            "source_type": "web",
                            "source_provider": "tavily",
                            "retrieval_method": "search",
                            "source_id": "src-tavily",
                            "title": "Source A",
                            "url": "https://example.com/a",
                            "origin_url": "https://example.com/a",
                        },
                        {
                            "source_type": "web",
                            "source_provider": "searxng",
                            "retrieval_method": "search",
                            "source_id": "src-searxng",
                            "title": "Source B",
                            "url": "https://example.com/b",
                            "origin_url": "https://example.com/b",
                        },
                    ],
                }
            }

    fake_model = object()
    runtime = SimpleNamespace(
        agent=_FakeAgent(),
        config=ResearchRuntimeConfig(
            primary_model=fake_model,
            subagent_model=fake_model,
            finalizer_model=fake_model,
            system_prompt="runtime prompt",
        ),
        tool_groups={"web_provider_ids": ("tavily", "searxng")},
        tools=[],
        make_run_config=lambda *, thread_id: {"configurable": {"thread_id": thread_id}},
    )
    runner = DeepResearchRuntimeRunner(runtime=runtime, workspace_files={})
    session = SimpleNamespace(
        id="session-123",
        thread_id="thread-123",
        trace_id="trace-123",
        question="How should DeepAgents runtime context be propagated?",
        artifacts=[],
    )

    await runner.run_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    runtime_context = captured["context"]
    assert runtime_context is not None
    assert runtime_context.session_id == "session-123"
    assert runtime_context.thread_id == "thread-123"
    assert runtime_context.trace_id == "trace-123"
    assert runtime_context.target_sources == ("web",)
    assert runtime_context.subagent_route == ("web", "citation")
    assert runtime_context.workspace_root.endswith("/session-123")
    assert runtime_context.scratch_root.endswith("/session-123")
