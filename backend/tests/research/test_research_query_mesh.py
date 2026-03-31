from __future__ import annotations

from app.schemas.research import ResearchPlanSnapshot, ResearchPlanSubtask, ResearchSourceTarget
from app.services.research_query_mesh import build_research_query_mesh, evaluate_coverage_gate


def _comparative_plan() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="比较 OpenAI、Gemini、Perplexity 的深度研究工作流。",
        complexity="comparative",
        summary="先广度召回，再做 claim verification。",
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        subtasks=[
            ResearchPlanSubtask(
                title="对比产品形态",
                description="分析 plan-first、evidence、report 交互。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )


def test_build_research_query_mesh_produces_verification_queries() -> None:
    mesh = build_research_query_mesh(
        question="对比 OpenAI、Gemini、Perplexity 的 Deep Research 方案",
        plan_snapshot=_comparative_plan(),
    )

    assert mesh.canonical_query.startswith("对比 OpenAI")
    assert len(mesh.breadth_queries) >= 2
    assert len(mesh.depth_queries) >= 1
    assert len(mesh.verification_queries) >= 1


def test_evaluate_coverage_gate_blocks_complex_runs_without_enough_providers() -> None:
    gate = evaluate_coverage_gate(
        complexity="complex",
        provider_counts={"tavily": 3, "jina_reader": 1},
        unique_source_count=6,
        source_types={"web"},
    )

    assert gate.passed is False
    assert "missing_web_provider_count" in gate.reasons
    assert "paper_source_missing" in gate.reasons
