from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_event_store import ResearchEventStore
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_planner import ResearchPlanner, ResearchScoper
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_service import ResearchService
from app.services.research_source_bundle import ResearchSourceBundleBuilder


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


class _FakeRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        return ResearchRuntimeRunResult(
            source_bundle=ResearchSourceBundleBuilder().build(
                target_sources=plan_snapshot.target_sources,
                citations=[],
                findings=[f"已完成问题“{session.question}”的 runtime 执行。"],
                required_web_providers=("tavily",),
            ),
            latency_ms=900,
            total_cost_usd=0.0,
        )


class _SequenceScoper(ResearchScoper):
    def __init__(self, outputs: list[ResearchClarificationRequest | ResearchPlanSnapshot]) -> None:
        self.outputs = list(outputs)
        self.questions: list[str] = []

    async def scope(
        self,
        *,
        question: str,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
        self.questions.append(question)
        if not self.outputs:
            raise AssertionError("missing scoper output")
        return self.outputs.pop(0)


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="围绕 LangGraph StateGraph 的核心概念与代码审查场景展开研究。",
        complexity=ResearchComplexity.COMPARATIVE,
        summary="先梳理核心概念，再对齐代码审查场景中的使用边界。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="核心概念",
                description="整理 StateGraph 的关键抽象。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
            ResearchPlanSubtask(
                title="代码审查场景",
                description="聚焦代码审查场景下的价值与边界。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
        ],
        budget_guidance="优先官方文档与可信实现资料。",
    )


def _assert_session_bootstrap_artifacts(session: ResearchSession) -> None:
    artifact_keys = [artifact.artifact_key for artifact in session.artifacts]
    assert artifact_keys[-5:] == [
        "mission_md",
        "plan_md",
        "query_map_md",
        "coverage_md",
        "report_draft_md",
    ]


@pytest.mark.asyncio
async def test_create_session_persists_plan_snapshot_artifact_event_and_queues_immediately() -> None:
    db = _FakeAsyncSession()
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(scoper=_SequenceScoper([_build_plan_snapshot()])),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )

    session, plan_result = await service.create_session(
        ResearchSessionCreateRequest(question="对比 Tavily 与 SearXNG 在深度研究网页检索中的优缺点"),
        thread_id="research-session-1",
    )

    assert db.flushed is True
    assert session.thread_id == "research-session-1"
    assert session.status == ResearchSessionStatus.QUEUED
    assert session.last_event_sequence == 1
    assert session.events[0].event_type == "research.plan.created"
    assert [artifact.artifact_key for artifact in session.artifacts] == [
        "plan_snapshot",
        "research_brief",
        "mission_md",
        "plan_md",
        "query_map_md",
        "coverage_md",
        "report_draft_md",
    ]
    _assert_session_bootstrap_artifacts(session)
    assert session.artifacts[1].content_text == plan_result.plan_snapshot.research_brief
    assert plan_result.auto_approve is True


@pytest.mark.asyncio
async def test_create_session_persists_workspace_bootstrap_artifacts() -> None:
    session_id = uuid4()
    db = AsyncMock()
    db.add = Mock()
    db.flush = AsyncMock()
    planner = AsyncMock()
    runtime_runner = AsyncMock()
    finalizer = AsyncMock()
    event_store = AsyncMock()
    artifact_store = AsyncMock()

    planner.build_plan.return_value = ResearchPlannerResult(
        plan_snapshot=ResearchPlanSnapshot(
            research_brief="构建 Deep Research OS。",
            complexity="complex",
            summary="生成计划、覆盖矩阵与最终工作台。",
            target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
            subtasks=[
                ResearchPlanSubtask(
                    title="生成研究计划",
                    description="产出 plan.md 与 query-map.md。",
                    target_sources=[ResearchSourceTarget.WEB],
                )
            ],
        ),
        clarification_request=None,
        auto_approve=True,
        next_status=ResearchSessionStatus.QUEUED,
    )

    service = ResearchService(
        db=db,
        planner=planner,
        runtime_runner=runtime_runner,
        finalizer=finalizer,
        event_store=event_store,
        artifact_store=artifact_store,
    )

    session, _ = await service.create_session(
        ResearchSessionCreateRequest(question="把 Deep Research 重做成 OS"),
        thread_id=str(session_id),
        session_id=session_id,
    )

    persisted_keys = [
        call.kwargs["artifact_key"] for call in artifact_store.upsert.await_args_list
    ]
    assert "mission_md" in persisted_keys
    assert "plan_md" in persisted_keys
    assert "coverage_md" in persisted_keys
    assert session.status == ResearchSessionStatus.QUEUED


@pytest.mark.asyncio
async def test_execute_session_runs_runtime_finalizer_and_writes_final_artifacts() -> None:
    db = _FakeAsyncSession()
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(scoper=_SequenceScoper([_build_plan_snapshot()])),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        id=uuid4(),
        thread_id="research-session-2",
        question="解释 Jina Reader 在深度研究中的作用",
        status=ResearchSessionStatus.QUEUED,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="以网页资料为主，解释 Jina Reader 的引用约束。",
        complexity="simple",
        summary="优先网页工具，最后走 finalizer。",
        target_sources=[ResearchSourceTarget.WEB],
    )

    final_result = await service.execute_session(
        session=session,
        plan_snapshot=plan_snapshot,
    )

    assert session.status == ResearchSessionStatus.FINAL
    assert [event.event_type for event in session.events] == [
        "research.run.started",
        "research.finalizer.started",
        "research.final.completed",
    ]
    artifact_keys = [artifact.artifact_key for artifact in session.artifacts]
    assert artifact_keys == [
        "source_bundle",
        "interim_findings",
        "interim_summary",
        "coverage_gaps",
        "report_json",
        "report_md",
        "metrics_snapshot",
        "gate_snapshot",
    ]
    assert final_result.report_json["question"] == "解释 Jina Reader 在深度研究中的作用"
    assert (session.metrics or {})["gate"]["pass"] is False


@pytest.mark.asyncio
async def test_event_store_reuses_existing_event_for_same_event_id() -> None:
    session = ResearchSession(
        thread_id="research-session-events",
        question="验证 event store 幂等",
        status=ResearchSessionStatus.CREATED,
    )
    store = ResearchEventStore(db=_FakeAsyncSession())

    first = await store.append(
        session=session,
        event_id="evt-fixed",
        event_type="research.plan.created",
        phase="planner",
        payload={"status": "first"},
    )
    second = await store.append(
        session=session,
        event_id="evt-fixed",
        event_type="research.plan.created",
        phase="planner",
        payload={"status": "second"},
    )

    assert second is first
    assert session.last_event_sequence == 1
    assert len(session.events) == 1
    assert session.events[0].payload == {"status": "first"}


@pytest.mark.asyncio
async def test_submit_clarification_transitions_to_queued_and_persists_plan() -> None:
    db = _FakeAsyncSession()
    scoper = _SequenceScoper(
        [
            ResearchClarificationRequest(
                summary="需要先明确研究场景。",
                questions=[
                    ResearchClarificationQuestion(
                        id="scope",
                        question="你更关注入门学习还是代码审查场景？",
                        why_it_matters="目标不同会影响研究结构。",
                    )
                ],
            ),
            _build_plan_snapshot(),
        ]
    )
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(scoper=scoper),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )

    session, _ = await service.create_session(
        ResearchSessionCreateRequest(question="帮我研究一下 AI 编程工具"),
        thread_id="research-session-clarify",
    )

    assert session.status == ResearchSessionStatus.CLARIFYING

    session, plan_result = await service.submit_clarification(
        session=session,
        answer="关注 LangGraph StateGraph 在代码审查场景的使用建议",
    )

    assert session.question == "帮我研究一下 AI 编程工具"
    assert session.status == ResearchSessionStatus.QUEUED
    assert plan_result.plan_snapshot is not None
    assert plan_result.clarification_request is None
    _assert_session_bootstrap_artifacts(session)
    assert scoper.questions == [
        "帮我研究一下 AI 编程工具",
        "帮我研究一下 AI 编程工具 关注 LangGraph StateGraph 在代码审查场景的使用建议",
    ]


@pytest.mark.asyncio
async def test_submit_clarification_accumulates_previous_answers_before_reaching_queued() -> None:
    db = _FakeAsyncSession()
    scoper = _SequenceScoper(
        [
            ResearchClarificationRequest(
                summary="需要先明确范围。",
                questions=[
                    ResearchClarificationQuestion(
                        id="scope",
                        question="你要做什么方向？",
                        why_it_matters="需要锁定范围。",
                    )
                ],
            ),
            ResearchClarificationRequest(
                summary="还需要补充具体场景。",
                questions=[
                    ResearchClarificationQuestion(
                        id="scene",
                        question="你要关注哪个具体场景？",
                        why_it_matters="需要场景才能输出有用计划。",
                    )
                ],
            ),
            _build_plan_snapshot(),
        ]
    )
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(scoper=scoper),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )

    session, _ = await service.create_session(
        ResearchSessionCreateRequest(question="帮我研究一下 AI 编程工具"),
        thread_id="research-session-clarify-2",
    )

    assert session.status == ResearchSessionStatus.CLARIFYING

    session, plan_result = await service.submit_clarification(
        session=session,
        answer="想了解入门选择",
    )

    assert plan_result.clarification_request is not None
    assert plan_result.plan_snapshot is None
    assert session.status == ResearchSessionStatus.CLARIFYING

    session, plan_result = await service.submit_clarification(
        session=session,
        answer="关注 LangGraph StateGraph 在代码审查场景的使用建议",
    )

    assert session.status == ResearchSessionStatus.QUEUED
    assert plan_result.plan_snapshot is not None
    assert plan_result.clarification_request is None
    _assert_session_bootstrap_artifacts(session)
    assert scoper.questions == [
        "帮我研究一下 AI 编程工具",
        "帮我研究一下 AI 编程工具 想了解入门选择",
        "帮我研究一下 AI 编程工具 想了解入门选择 关注 LangGraph StateGraph 在代码审查场景的使用建议",
    ]


@pytest.mark.asyncio
async def test_interrupt_and_resume_session_are_stateful_and_idempotent() -> None:
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(scoper=_SequenceScoper([_build_plan_snapshot()])),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        thread_id="research-session-3",
        question="解释 interrupt / resume 语义",
        status=ResearchSessionStatus.RUNNING,
    )

    await service.interrupt_session(
        session=session,
        reason="等待人工确认",
    )
    first = await service.resume_session(
        session=session,
        idempotency_key="resume-1",
        resume_from_event_id="evt-000001",
        decisions=[{"action": "approve"}],
    )
    second = await service.resume_session(
        session=session,
        idempotency_key="resume-1",
        resume_from_event_id="evt-should-not-overwrite",
        decisions=[{"action": "reject"}],
    )

    assert session.status == ResearchSessionStatus.RESUMING
    assert [event.event_type for event in session.events] == [
        "research.run.interrupted",
        "research.run.resume_requested",
    ]
    assert first == {
        "status": "accepted",
        "resume_from_event_id": "evt-000001",
        "decision_count": 1,
    }
    assert second == first
    assert session.last_resume_idempotency_key == "resume-1"
    assert session.last_resume_response == first
