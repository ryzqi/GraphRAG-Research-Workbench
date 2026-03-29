from __future__ import annotations

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchPlanSnapshot,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_event_store import ResearchEventStore
from app.services.research_finalizer import ResearchFinalizer
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
    ):
        return ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=[],
            findings=[f"已完成问题“{session.question}”的 runtime 执行。"],
            required_web_providers=("tavily",),
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
            allow_external=True,
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
        thread_id="research-session-2",
        question="解释 Jina Reader 在深度研究中的作用",
        allow_external=True,
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
    ]
    assert final_result.report_json["question"] == "解释 Jina Reader 在深度研究中的作用"


async def test_event_store_reuses_existing_event_for_same_event_id() -> None:
    session = ResearchSession(
        thread_id="research-session-events",
        question="验证 event store 幂等",
        allow_external=False,
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
        thread_id="research-session-confirm",
        question="确认计划",
        allow_external=True,
        status=ResearchSessionStatus.AWAITING_CONFIRMATION,
    )

    await service.confirm_plan(
        session=session,
        approved=True,
        note="继续执行",
    )

    assert session.status == ResearchSessionStatus.QUEUED
    assert session.events[0].event_type == "research.plan.confirmed"
    assert session.events[0].payload == {"approved": True, "note": "继续执行"}


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
        allow_external=False,
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
