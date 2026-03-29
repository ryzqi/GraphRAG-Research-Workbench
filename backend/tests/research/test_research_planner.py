from __future__ import annotations

from uuid import uuid4

from app.schemas.research import ResearchComplexity, ResearchSessionCreateRequest, ResearchSourceTarget
from app.services.research_planner import ResearchPlanner


def test_simple_research_request_gets_auto_approved_kb_plan() -> None:
    planner = ResearchPlanner()

    plan = planner.build_plan(
        ResearchSessionCreateRequest(
            question="总结内部知识库里关于 LangGraph StateGraph 的核心概念",
            selected_kb_ids=[uuid4()],
            allow_external=False,
        )
    )

    assert plan.plan_snapshot.complexity == ResearchComplexity.SIMPLE
    assert plan.plan_snapshot.target_sources == [ResearchSourceTarget.KB]
    assert plan.plan_snapshot.confirmation_required is False
    assert plan.auto_approve is True
    assert plan.plan_artifact_key == "plan_snapshot"


def test_comparative_research_request_requires_confirmation() -> None:
    planner = ResearchPlanner()

    plan = planner.build_plan(
        ResearchSessionCreateRequest(
            question="对比 Tavily 与 SearXNG 在深度研究网页检索中的优缺点",
            selected_kb_ids=None,
            allow_external=True,
        )
    )

    assert plan.plan_snapshot.complexity == ResearchComplexity.COMPARATIVE
    assert plan.plan_snapshot.target_sources == [ResearchSourceTarget.WEB]
    assert plan.plan_snapshot.confirmation_required is True
    assert plan.auto_approve is False
    assert len(plan.plan_snapshot.subtasks) >= 2


def test_complex_hybrid_research_request_prioritizes_hybrid_route() -> None:
    planner = ResearchPlanner()

    plan = planner.build_plan(
        ResearchSessionCreateRequest(
            question="做一份 2024-2026 Deep Research agent 论文与开源实现综述，并结合内部知识库总结落地建议",
            selected_kb_ids=[uuid4()],
            allow_external=True,
        )
    )

    assert plan.plan_snapshot.complexity == ResearchComplexity.COMPLEX
    assert plan.plan_snapshot.target_sources == [ResearchSourceTarget.HYBRID]
    assert plan.plan_snapshot.confirmation_required is True
    assert any(
        ResearchSourceTarget.PAPER in subtask.target_sources
        for subtask in plan.plan_snapshot.subtasks
    )
    assert plan.artifact_payload["research_brief"] == plan.plan_snapshot.research_brief
