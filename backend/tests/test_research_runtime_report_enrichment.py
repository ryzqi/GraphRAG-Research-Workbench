from __future__ import annotations

import json

from langchain.tools import tool as lc_tool

from app.prompts import get_prompt_loader
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.deep_research_runtime import _build_source_specialized_subagents
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import build_runtime_context_snapshot
from app.services.research_runtime_skills import build_research_runtime_skill_files
from app.services.research_runtime_types import ResearchRuntimeConfig
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_runtime_orchestration_scaffold_files,
)


@lc_tool("web_search")
def _web_search_tool(query: str) -> str:
    """测试用 web_search 工具。"""

    return query


@lc_tool("arxiv_search")
def _arxiv_search_tool(query: str) -> str:
    """测试用 arxiv_search 工具。"""

    return query


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot.model_validate(
        {
            "research_brief": "比较官方文档与运行时实现的差异，并产出高密度研究报告。",
            "complexity": "complex",
            "summary": "先拆 claim，再分 source 并行补证，最后回收章节与建议。",
            "subtasks": [
                {
                    "title": "对比 Deep Agents 与当前实现",
                    "description": "核对任务编排、子代理、上下文管理与消息传递。",
                    "target_sources": ["web", "paper"],
                }
            ],
            "target_sources": ["web", "paper"],
            "budget_guidance": "优先保证结论与证据映射完整。",
        }
    )


def _build_source_bundle() -> ResearchSourceBundle:
    return ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER),
        citations=[
            ResearchCanonicalCitation(
                source_type=ResearchSourceType.WEB,
                source_provider="tavily",
                retrieval_method="web_search",
                source_id="https://example.com/deepagents",
                title="Deep Agents Overview",
                url="https://example.com/deepagents",
                origin_url="https://example.com/deepagents",
            ),
            ResearchCanonicalCitation(
                source_type=ResearchSourceType.PAPER,
                source_provider="arxiv",
                retrieval_method="search",
                source_id="arxiv:2501.00001",
                title="Stateful Research Agents",
                url="https://arxiv.org/abs/2501.00001",
                origin_url="https://arxiv.org/abs/2501.00001",
                arxiv_id="2501.00001",
                pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
            ),
        ],
        findings=[
            "Deep Agents 的 research workflow 需要先计划，再对子议题并行委派子代理。",
            "LangGraph 持久连续性依赖稳定 thread_id 与 checkpointer。",
        ],
        interim_summary="当前实现已具备基础 research runtime，但报告密度仍偏低。",
        coverage_gaps=["缺少对子代理 handoff packet 的统一约束。"],
        provider_counts={"tavily": 1, "arxiv": 1},
    )


def test_runtime_orchestration_scaffold_seeds_rich_research_contract() -> None:
    layout = build_research_workspace_layout("session-1")
    files = build_runtime_orchestration_scaffold_files(
        question="如何让 deep research 报告更丰富？",
        plan_snapshot=_build_plan_snapshot(),
        layout=layout,
    )

    report_context = json.loads(files[layout.report_context_json_path])
    task_graph = json.loads(files[layout.task_graph_path])
    claim_bundles = json.loads(files[layout.claim_bundles_path])
    section_briefs = json.loads(files[layout.section_briefs_path])

    assert report_context["key_takeaways"] == []
    assert report_context["recommended_actions"] == []
    assert {task["task_kind"] for task in task_graph["tasks"]} >= {
        "claim",
        "source",
        "section",
    }
    assert any(task.get("owner") == "web" for task in task_graph["tasks"])
    assert any(task.get("owner") == "paper" for task in task_graph["tasks"])
    assert claim_bundles[0]["claim_id"] == "claim-1"
    assert "counter_evidence" in claim_bundles[0]
    assert "must_cover" in section_briefs[0]
    assert "evidence_targets" in section_briefs[0]


def test_runtime_prompts_and_subagents_require_role_specific_handoffs() -> None:
    config = ResearchRuntimeConfig(
        primary_model=object(),
        subagent_model=object(),
        finalizer_model=object(),
        system_prompt="BASE SYSTEM PROMPT",
    )
    subagents = _build_source_specialized_subagents(
        config=config,
        tools=[_web_search_tool, _arxiv_search_tool],
        tool_groups={
            "web": ("web_search",),
            "paper": ("arxiv_search",),
            "citation": (),
        },
        resolved_skill_paths=("/skills/",),
    )

    web_subagent = next(item for item in subagents if item["name"] == "web")
    section_subagent = next(item for item in subagents if item["name"] == "section-writer")
    runtime_skills = build_research_runtime_skill_files()
    runtime_prompt = get_prompt_loader().render(
        "research/runtime_user",
        question="如何优化 deep research 报告？",
        research_brief="围绕报告质量优化当前实现。",
        target_sources="web, paper",
        route_hint="web, paper, claim-verifier, section-writer, citation",
        workspace_paths_block="- /workspace/context/runtime_context_guide.md",
    )

    assert "网页来源子代理" in web_subagent["system_prompt"]
    assert "只消费已验证工件" in section_subagent["system_prompt"]
    assert "handoff" in runtime_skills["/skills/research-runtime/SKILL.md"].lower()
    assert "before any external search" not in runtime_skills["/skills/research-runtime/SKILL.md"].lower()
    assert "handoff" in runtime_prompt.lower()


def test_runtime_snapshot_and_finalizer_surface_richer_runtime_payload() -> None:
    layout = build_research_workspace_layout("session-1")
    snapshot = build_runtime_context_snapshot(
        result={
            "todos": [
                {"content": "核对官网与论文口径", "status": "completed"},
                {"content": "补写章节简报与建议", "status": "in_progress"},
            ],
            "files": {
                layout.report_context_json_path: {
                    "content": json.dumps(
                        {
                            "executive_summary": "报告应先给出结论，再明确证据与限制。",
                            "confidence_level": "partial",
                            "has_conflicts": True,
                            "key_takeaways": [
                                "需要更细粒度的任务分解与 richer report context。"
                            ],
                            "recommended_actions": [
                                "把 claim/source/section 任务显式写入 task graph。"
                            ],
                            "verification_notes": ["已做官方文档交叉验证。"],
                            "open_questions": ["是否还需要单独的 citation audit task？"],
                        },
                        ensure_ascii=False,
                    )
                },
                layout.task_graph_path: {
                    "content": json.dumps(
                        {
                            "tasks": [
                                {
                                    "task_id": "claim-1",
                                    "title": "收口主张",
                                    "task_kind": "claim",
                                    "status": "completed",
                                    "owner": "claim-verifier",
                                },
                                {
                                    "task_id": "section-1",
                                    "title": "扩写章节",
                                    "task_kind": "section",
                                    "status": "in_progress",
                                    "owner": "section-writer",
                                },
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
                layout.claim_bundles_path: {
                    "content": json.dumps(
                        [
                            {
                                "claim_id": "claim-1",
                                "section_id": "section-1",
                                "claim": "更丰富的报告依赖 richer runtime artifacts。",
                                "status": "supported",
                                "evidence": [
                                    "官方 Deep Agents workflow 强调先计划、再委派、再综合。"
                                ],
                                "counter_evidence": ["仅改模板无法提高实际信息密度。"],
                                "limitations": ["当前 handoff packet 仍未标准化。"],
                                "citation_indices": [1, 2],
                            }
                        ],
                        ensure_ascii=False,
                    )
                },
                layout.section_briefs_path: {
                    "content": json.dumps(
                        [
                            {
                                "section_id": "section-1",
                                "task_id": "section-1",
                                "title": "编排与上下文管理",
                                "status": "in_progress",
                                "summary": "需要把 claim/source/section 分工提前结构化。",
                                "brief_markdown": "### 编排建议\n先拆任务，再并行补证，最后统一收口。",
                                "must_cover": ["任务分解", "子代理", "消息传递"],
                                "evidence_targets": ["官方 Deep Agents 文档", "当前 runtime 实现"],
                                "open_questions": ["citation audit 是否独立建 task？"],
                                "citation_indices": [1, 2],
                            }
                        ],
                        ensure_ascii=False,
                    )
                },
                layout.live_board_path: {
                    "content": json.dumps(
                        {
                            "recent_activity": [
                                {
                                    "task_id": "claim-1",
                                    "title": "收口主张",
                                    "task_kind": "claim",
                                    "status": "completed",
                                    "agent_label": "claim-verifier",
                                    "message": "已完成官方约束核对。",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
            },
        },
        layout=layout,
    )

    assert snapshot is not None
    assert snapshot.todos_json[0]["content"] == "核对官网与论文口径"

    compiled = compile_report_from_runtime_context(
        question="如何让 deep research 报告更丰富？",
        source_bundle=_build_source_bundle(),
        runtime_context_snapshot=snapshot,
    )

    assert compiled is not None
    assert "关键要点" in compiled.report_md
    assert "待办执行" in compiled.report_md
    assert "已完成官方约束核对" in compiled.report_md

    finalizer = ResearchFinalizer()
    result = finalizer.finalize(
        question="如何让 deep research 报告更丰富？",
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        source_bundle=_build_source_bundle(),
        runtime_context_snapshot=snapshot,
    )

    assert "report_md" not in result.report_json
    assert "runtime_context" not in result.report_json
    assert "task_graph" not in result.report_json
    assert "claim_bundles" not in result.report_json
    assert "section_briefs" not in result.report_json
    assert "live_board" not in result.report_json
    assert "todos" not in result.report_json
    assert result.report_json["summary"] == "报告应先给出结论，再明确证据与限制。"
