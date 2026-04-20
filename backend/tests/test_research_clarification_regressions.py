from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from app.core.errors import AppError
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchClarificationRequest,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_planner import ResearchPlanner
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_service import ResearchService
from app.services.research_service_session_ops import submit_clarification


def _build_session_with_events() -> ResearchSession:
    session = ResearchSession(
        thread_id="session-thread",
        question="当前RAG领域的最新研究",
        status=ResearchSessionStatus.CLARIFYING,
        planner_phase="preflight",
    )
    session.trace_id = "research:session-thread"
    session.events = [
        ResearchEvent(
            event_id="evt-1",
            sequence=1,
            event_type="research.clarification.requested",
            phase="planner",
            namespace="main",
            payload={
                "summary": "需要先收敛时间范围与研究重点。",
                "questions": [
                    {
                        "id": "q1",
                        "question": "你想看哪个时间范围？",
                        "why_it_matters": "影响最新研究的时间边界。",
                    }
                ],
            },
        ),
        ResearchEvent(
            event_id="evt-2",
            sequence=2,
            event_type="research.clarification.submitted",
            phase="planner",
            namespace="main",
            payload={"answer": "最近6个月"},
        ),
        ResearchEvent(
            event_id="evt-3",
            sequence=3,
            event_type="research.clarification.requested",
            phase="planner",
            namespace="main",
            payload={
                "summary": "还缺少比较维度。",
                "questions": [
                    {
                        "id": "q2",
                        "question": "你要比较哪些RAG方向？",
                        "why_it_matters": "影响研究计划的比较轴。",
                    }
                ],
            },
        ),
    ]
    session.artifacts = []
    session.task_outbox_entries = []
    return session


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="围绕近6个月的RAG检索增强技术进行综述。",
        summary="已可以直接开始研究。",
        complexity="comparative",
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        subtasks=[
            ResearchPlanSubtask(
                title="收集最新论文",
                description="梳理GraphRAG、多跳检索、Agentic RAG与长上下文RAG。",
                target_sources=[ResearchSourceTarget.PAPER],
            )
        ],
    )


@pytest.mark.asyncio
async def test_submit_clarification_disables_follow_up_when_current_answer_reaches_max_rounds() -> None:
    session = _build_session_with_events()
    recorded: dict[str, object] = {}

    async def build_plan(
        request: ResearchSessionCreateRequest,
        *,
        allow_clarify: bool = True,
    ) -> ResearchPlannerResult:
        recorded["question"] = request.question
        recorded["allow_clarify"] = allow_clarify
        return ResearchPlannerResult(
            plan_snapshot=_build_plan_snapshot(),
            clarification_request=None,
            next_status=ResearchSessionStatus.PLAN_READY,
        )

    async def persist_answer(*, session: ResearchSession, answer: str) -> None:
        recorded["persisted_answer"] = answer

    async def append_event(**kwargs: object) -> None:
        recorded.setdefault("appended_events", []).append(kwargs)

    async def persist_plan_artifacts(
        *,
        session: ResearchSession,
        plan_result: ResearchPlannerResult,
    ) -> None:
        recorded["plan_artifacts_written"] = plan_result.plan_snapshot is not None

    service = SimpleNamespace(
        _planner=SimpleNamespace(build_plan=build_plan),
        _event_store=SimpleNamespace(append=append_event),
        _persist_clarification_answer=persist_answer,
        _persist_clarification_request=None,
        _persist_planned_session_artifacts=persist_plan_artifacts,
        _ensure_dispatch_outbox=lambda *, session: recorded.setdefault(
            "dispatch_outbox_called", session.status
        ),
        _should_allow_follow_up_clarification=ResearchService._should_allow_follow_up_clarification,
        _build_effective_planning_question=ResearchService._build_effective_planning_question,
    )

    result_session, plan_result = await submit_clarification(
        service,
        session=session,
        answer="重点比较 GraphRAG、多跳检索、Agentic RAG 与长上下文 RAG。",
    )

    assert recorded["allow_clarify"] is False
    assert "当前澄清回答轮次：2 / 2。" in recorded["question"]
    assert result_session.status == ResearchSessionStatus.PLAN_READY
    assert plan_result.plan_snapshot is not None


@pytest.mark.asyncio
async def test_research_planner_maps_openai_connection_error_to_app_error() -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8080/v1/chat/completions")

    class FailingScoper:
        async def scope(
            self,
            *,
            question: str,
            allow_clarify: bool = True,
        ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
            del question, allow_clarify
            raise APIConnectionError(message="Connection error.", request=request)

    planner = ResearchPlanner(scoper=FailingScoper())

    with pytest.raises(AppError, match="大模型服务连接失败"):
        await planner.build_plan(
            ResearchSessionCreateRequest(question="当前RAG领域的最新研究"),
            allow_clarify=True,
        )


@pytest.mark.asyncio
async def test_research_planner_maps_invalid_schema_to_app_error() -> None:
    class FailingScoper:
        async def scope(
            self,
            *,
            question: str,
            allow_clarify: bool = True,
        ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
            del question, allow_clarify
            raise RuntimeError(
                "Research scoper structured output 解析失败: function_calling:invalid_schema"
            )

    planner = ResearchPlanner(scoper=FailingScoper())

    with pytest.raises(AppError, match="研究计划结构化输出解析失败"):
        await planner.build_plan(
            ResearchSessionCreateRequest(question="当前RAG领域的最新研究"),
            allow_clarify=True,
        )
