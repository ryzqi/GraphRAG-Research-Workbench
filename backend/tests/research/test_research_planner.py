from __future__ import annotations

import pytest

from app.models.research_session import ResearchSessionStatus
from app.schemas.research import (
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_planner import ResearchPlanner, ResearchScoper


class _StaticScoper(ResearchScoper):
    def __init__(
        self,
        result: ResearchClarificationRequest | ResearchPlanSnapshot,
    ) -> None:
        self.result = result
        self.questions: list[str] = []

    async def scope(
        self,
        *,
        question: str,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
        self.questions.append(question)
        return self.result


@pytest.mark.asyncio
async def test_planner_returns_clarification_request_when_scoper_requires_more_context() -> None:
    scoper = _StaticScoper(
        ResearchClarificationRequest(
            summary="研究范围还不够清楚，需要先补充目标场景。",
            questions=[
                ResearchClarificationQuestion(
                    id="scope",
                    question="你更关注个人使用建议，还是团队落地方案？",
                    why_it_matters="目标不同会直接影响研究维度和输出结构。",
                )
            ],
        )
    )
    planner = ResearchPlanner(scoper=scoper)

    result = await planner.build_plan(
        ResearchSessionCreateRequest(question="帮我研究一下 AI 编程工具")
    )

    assert scoper.questions == ["帮我研究一下 AI 编程工具"]
    assert result.clarification_request is not None
    assert result.plan_snapshot is None
    assert result.next_status == ResearchSessionStatus.CLARIFYING
    assert result.auto_approve is True


@pytest.mark.asyncio
async def test_planner_returns_queued_plan_snapshot_when_scoper_can_proceed() -> None:
    scoper = _StaticScoper(
        ResearchPlanSnapshot(
            research_brief="围绕 LangGraph StateGraph 的核心概念与适用边界展开研究。",
            complexity=ResearchComplexity.SIMPLE,
            summary="直接整理核心概念、关键机制与典型适用场景。",
            target_sources=[ResearchSourceTarget.WEB],
            subtasks=[
                ResearchPlanSubtask(
                    title="梳理核心概念",
                    description="整理 StateGraph 的关键抽象与运行模型。",
                    target_sources=[ResearchSourceTarget.WEB],
                )
            ],
            budget_guidance="优先官方文档与权威教程。",
        )
    )
    planner = ResearchPlanner(scoper=scoper)

    result = await planner.build_plan(
        ResearchSessionCreateRequest(question="介绍一下 LangGraph StateGraph 的核心概念")
    )

    assert result.clarification_request is None
    assert result.plan_snapshot is not None
    assert result.plan_snapshot.target_sources == [ResearchSourceTarget.WEB]
    assert result.next_status == ResearchSessionStatus.QUEUED
    assert result.auto_approve is True

