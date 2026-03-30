from __future__ import annotations

from uuid import uuid4

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchPlanSnapshot,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_event_store import ResearchEventStore
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_planner import ResearchPlanner
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


async def test_create_session_persists_plan_snapshot_artifact_and_event() -> None:
    db = _FakeAsyncSession()
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )

    session, plan_result = await service.create_session(
        ResearchSessionCreateRequest(
            question="对比 Tavily 与 SearXNG 在深度研究网页检索中的优缺点",
        ),
        thread_id="research-session-1",
    )

    assert db.flushed is True
    assert session.thread_id == "research-session-1"
    assert session.status == ResearchSessionStatus.AWAITING_CONFIRMATION
    assert session.last_event_sequence == 1
    assert session.events[0].event_type == "research.plan.created"
    assert [artifact.artifact_key for artifact in session.artifacts] == [
        "plan_snapshot",
        "research_brief",
    ]
    assert session.artifacts[1].content_text == plan_result.plan_snapshot.research_brief
    assert plan_result.plan_snapshot.confirmation_required is True


async def test_execute_session_runs_runtime_finalizer_and_writes_final_artifacts() -> None:
    db = _FakeAsyncSession()
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(),
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
        confirmation_required=False,
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


async def test_confirm_plan_queues_session_and_appends_confirmation_event() -> None:
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(),
        runtime_runner=_FakeRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        id=uuid4(),
        thread_id="research-session-confirm",
        question="确认计划",
        status=ResearchSessionStatus.AWAITING_CONFIRMATION,
    )

    await service.confirm_plan(
        session=session,
        approved=True,
        note="继续执行",
    )

    assert session.status == ResearchSessionStatus.QUEUED
    assert session.events[0].event_type == "research.plan.confirmed"
    assert session.events[0].payload == {
        "approved": True,
        "note": "继续执行",
        "lc_agent_name": "planner",
    }


async def test_submit_clarification_transitions_to_awaiting_confirmation() -> None:
    db = _FakeAsyncSession()
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(),
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
    assert session.status == ResearchSessionStatus.AWAITING_CONFIRMATION
    assert plan_result.plan_snapshot is not None
    assert plan_result.clarification_request is None
    assert "补充说明：" not in plan_result.plan_snapshot.research_brief


async def test_submit_clarification_accumulates_previous_answers() -> None:
    db = _FakeAsyncSession()
    service = ResearchService(
        db=db,
        planner=ResearchPlanner(),
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

    assert session.question == "帮我研究一下 AI 编程工具"
    assert plan_result.clarification_request is not None
    assert plan_result.plan_snapshot is None
    assert session.status == ResearchSessionStatus.CLARIFYING

    session, plan_result = await service.submit_clarification(
        session=session,
        answer="关注 LangGraph StateGraph 在代码审查场景的使用建议",
    )

    assert session.question == "帮我研究一下 AI 编程工具"
    assert session.status == ResearchSessionStatus.AWAITING_CONFIRMATION
    assert plan_result.plan_snapshot is not None
    assert plan_result.clarification_request is None
    assert "想了解入门选择" in plan_result.plan_snapshot.research_brief
    assert "关注 LangGraph StateGraph 在代码审查场景的使用建议" in (
        plan_result.plan_snapshot.research_brief
    )
    assert "补充说明：" not in plan_result.plan_snapshot.research_brief


async def test_interrupt_and_resume_session_are_stateful_and_idempotent() -> None:
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(),
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
