from __future__ import annotations

import asyncio
import uuid

from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession
from app.models.research_session import ResearchSessionStatus
from app.schemas.research import (
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.prompts import get_prompt_loader
from app.services.research_artifact_store import ResearchArtifactStore
from app.services.research_event_store import ResearchEventStore
from app.services.research_planner import LLMResearchScoper, ResearchPlanner
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_service import ResearchService


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="围绕 LangGraph 的入门、适用边界与迁移建议开展研究。",
        complexity="comparative",
        summary="按既定边界生成研究计划。",
        subtasks=[
            ResearchPlanSubtask(
                title="收集一手资料",
                description="优先核对官方文档与近期实践。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
        target_sources=[ResearchSourceTarget.WEB],
        budget_guidance="若存在轻微模糊，采用保守假设继续。",
    )


class _RecordingScoper:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def scope(
        self,
        *,
        question: str,
        allow_clarify: bool = True,
    ) -> ResearchPlanSnapshot:
        self.calls.append((question, allow_clarify))
        return _build_plan_snapshot()


def test_research_planner_forwards_allow_clarify_to_scoper() -> None:
    scoper = _RecordingScoper()
    planner = ResearchPlanner(scoper=scoper)

    result = asyncio.run(
        planner.build_plan(
            ResearchSessionCreateRequest(question="请研究 LangGraph 的适用边界"),
            allow_clarify=False,
        )
    )

    assert result.next_status == ResearchSessionStatus.PLAN_READY
    assert scoper.calls == [("请研究 LangGraph 的适用边界", False)]


class _DummyDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


class _PolicyAwarePlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def build_plan(
        self,
        request: ResearchSessionCreateRequest,
        *,
        allow_clarify: bool = True,
    ) -> ResearchPlannerResult:
        self.calls.append((request.question, allow_clarify))
        if allow_clarify:
            return ResearchPlannerResult(
                plan_snapshot=None,
                clarification_request=ResearchClarificationRequest(
                    summary="还缺少关键研究边界。",
                    questions=[
                        ResearchClarificationQuestion(
                            id="q1",
                            question="请一次性补充关注地区、时间范围和比较对象。",
                            why_it_matters="这些变量会直接改变研究路径。",
                        )
                    ],
                ),
                auto_approve=False,
                next_status=ResearchSessionStatus.CLARIFYING,
            )
        return ResearchPlannerResult(
            plan_snapshot=_build_plan_snapshot(),
            clarification_request=None,
            auto_approve=False,
            next_status=ResearchSessionStatus.PLAN_READY,
        )


def _build_service(planner: _PolicyAwarePlanner) -> ResearchService:
    db = _DummyDb()
    service = object.__new__(ResearchService)
    service._db = db
    service._planner = planner
    service._event_store = ResearchEventStore(db)
    service._artifact_store = ResearchArtifactStore(db)
    return service


def _build_session(
    *,
    status: ResearchSessionStatus = ResearchSessionStatus.CLARIFYING,
) -> ResearchSession:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id=f"thread-{uuid.uuid4()}",
        question="请研究 LangGraph 在企业知识库问答中的适用边界",
        status=status,
        trace_id="trace-1",
    )
    session.artifacts = []
    session.events = []
    session.task_outbox_entries = []
    return session


def test_submit_clarification_first_followup_leaves_decision_to_planner() -> None:
    planner = _PolicyAwarePlanner()
    service = _build_service(planner)
    session = _build_session()

    updated_session, result = asyncio.run(
        service.submit_clarification(
            session=session,
            answer="重点关注企业知识库场景，对比 LangGraph 与工作流编排方案，时间范围以近一年为主。",
        )
    )

    assert updated_session.status == ResearchSessionStatus.CLARIFYING
    assert result.clarification_request is not None
    assert result.plan_snapshot is None
    assert planner.calls[0][1] is True


def test_submit_clarification_second_followup_forces_plan_ready() -> None:
    planner = _PolicyAwarePlanner()
    service = _build_service(planner)
    session = _build_session()
    session.events = [
        ResearchEvent(
            session=session,
            event_id="evt-prior-answer",
            sequence=1,
            event_type="research.clarification.submitted",
            phase="planner",
            payload={"answer": "先关注中国和北美市场。"},
            trace_id="trace-1",
        )
    ]

    updated_session, result = asyncio.run(
        service.submit_clarification(
            session=session,
            answer="最终输出面向技术负责人。",
        )
    )

    assert updated_session.status == ResearchSessionStatus.PLAN_READY
    assert result.plan_snapshot is not None
    assert planner.calls[0][1] is False


def test_effective_planning_question_includes_structured_history_and_policy() -> None:
    session = _build_session()
    session.events = [
        ResearchEvent(
            session=session,
            event_id="evt-1",
            sequence=1,
            event_type="research.clarification.requested",
            phase="planner",
            payload={
                "summary": "还缺少研究边界。",
                "questions": [
                    {
                        "id": "q1",
                        "question": "请一次性补充关注地区、时间范围和比较对象。",
                        "why_it_matters": "这些变量会直接改变研究路径。",
                    }
                ],
            },
            trace_id="trace-1",
        ),
        ResearchEvent(
            session=session,
            event_id="evt-2",
            sequence=2,
            event_type="research.clarification.submitted",
            phase="planner",
            payload={"answer": "先关注中国和北美市场。"},
            trace_id="trace-1",
        ),
    ]

    effective_question = ResearchService._build_effective_planning_question(
        session=session,
        answer="最终输出希望给技术负责人看，时间范围聚焦近一年。",
    )

    assert "原始问题：" in effective_question
    assert "已发出的澄清问题：" in effective_question
    assert "已收到的澄清回答：" in effective_question
    assert "本轮补充：" in effective_question
    assert "规划策略：" in effective_question
    assert "默认直接生成研究计划" in effective_question


def test_scoper_prompts_prefer_single_round_aggregated_clarification() -> None:
    rendered_prompt = get_prompt_loader().render_with_few_shot(
        "research/scoper_user",
        question="请研究 LangGraph 的适用边界",
    )
    scoper = LLMResearchScoper()
    clarify_messages = scoper._build_clarify_messages(
        question="请研究 LangGraph 的适用边界",
        method="json_mode",
    )
    clarify_prompt = str(clarify_messages[1].content)

    assert "优先一次性收集所有会改变研究路径的关键缺口" in rendered_prompt
    assert "不要为时间范围、受众、输出形态等轻微模糊单独追问" in rendered_prompt
    assert "优先一次性收集所有会改变研究路径的关键缺口" in clarify_prompt
    assert "允许把多个剩余关键维度聚合为一次提问" in clarify_prompt
