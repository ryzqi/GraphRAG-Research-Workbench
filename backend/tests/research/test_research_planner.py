from __future__ import annotations

from app.models.research_session import ResearchSessionStatus
from app.schemas.research import ResearchComplexity, ResearchSessionCreateRequest, ResearchSourceTarget
from app.services.research_planner import ResearchPlanner


def test_simple_research_request_gets_auto_approved_web_plan() -> None:
    planner = ResearchPlanner()

    plan = planner.build_plan(
        ResearchSessionCreateRequest(
            question="总结 LangGraph StateGraph 的核心概念",
        )
    )

    assert plan.plan_snapshot.complexity == ResearchComplexity.SIMPLE
    assert plan.plan_snapshot.target_sources == [ResearchSourceTarget.WEB]
    assert plan.plan_snapshot.confirmation_required is True
    assert plan.auto_approve is False
    assert plan.plan_artifact_key == "plan_snapshot"


def test_comparative_research_request_requires_confirmation() -> None:
    planner = ResearchPlanner()

    plan = planner.build_plan(
        ResearchSessionCreateRequest(
            question="对比 Tavily 与 SearXNG 在深度研究网页检索中的优缺点",
        )
    )

    assert plan.plan_snapshot.complexity == ResearchComplexity.COMPARATIVE
    assert plan.plan_snapshot.target_sources == [ResearchSourceTarget.WEB]
    assert plan.plan_snapshot.confirmation_required is True
    assert plan.auto_approve is False
    assert len(plan.plan_snapshot.subtasks) >= 2


def test_complex_research_request_prioritizes_paper_and_web_route() -> None:
    planner = ResearchPlanner()

    plan = planner.build_plan(
        ResearchSessionCreateRequest(
            question="做一份 2024-2026 Deep Research agent 论文与开源实现综述，并总结落地建议",
        )
    )

    assert plan.plan_snapshot.complexity == ResearchComplexity.COMPLEX
    assert plan.plan_snapshot.target_sources == [
        ResearchSourceTarget.PAPER,
        ResearchSourceTarget.WEB,
    ]
    assert plan.plan_snapshot.confirmation_required is True
    assert any(
        ResearchSourceTarget.PAPER in subtask.target_sources
        for subtask in plan.plan_snapshot.subtasks
    )
    assert plan.artifact_payload["research_brief"] == plan.plan_snapshot.research_brief


def test_unclear_research_request_returns_clarification_instead_of_plan() -> None:
    planner = ResearchPlanner()
    result = planner.build_plan(
        ResearchSessionCreateRequest(question="帮我研究一下 AI 编程工具")
    )

    assert result.clarification_request is not None
    assert result.plan_snapshot is None
    assert result.next_status == ResearchSessionStatus.CLARIFYING
    assert result.auto_approve is False
