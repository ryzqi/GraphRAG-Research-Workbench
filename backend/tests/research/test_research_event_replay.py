from __future__ import annotations

from uuid import uuid4

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_observability import (
    ResearchRuntimeRunResult,
    ResearchTraceLink,
)
from app.services.research_planner import ResearchPlanner
from app.services.research_replay import (
    evaluate_research_replay_consistency,
    replay_research_session,
)
from app.services.research_service import ResearchService
from app.services.research_source_bundle import ResearchSourceBundleBuilder


class _FakeAsyncSession:
    def add(self, obj: object) -> None:
        del obj


class _ReplayRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        citation = ResearchCanonicalCitation(
            source_type=ResearchSourceType.PAPER,
            source_provider="arxiv",
            retrieval_method="fetch",
            source_id="arxiv:2501.00001",
            title="Replay Contract",
            url="https://arxiv.org/abs/2501.00001",
            origin_url="https://arxiv.org/abs/2501.00001",
            arxiv_id="2501.00001",
            authors=["Alice"],
            pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
        )
        bundle = ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=[citation],
            findings=[f"会话 {session.thread_id} 的事件可回放。", "终态与 event 序列一致。"],
            required_web_providers=(),
        )
        return ResearchRuntimeRunResult(
            source_bundle=bundle,
            trace_links=(ResearchTraceLink(lc_agent_name="paper", namespace="research/paper"),),
            latency_ms=2_000,
            total_cost_usd=0.6,
        )


async def test_replay_matches_terminal_session_state() -> None:
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(),
        runtime_runner=_ReplayRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        id=uuid4(),
        thread_id="research-replay-session",
        question="验证事件回放与终态一致性",
        allow_external=True,
        status=ResearchSessionStatus.QUEUED,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="先跑 paper，再验证 replay。",
        complexity="simple",
        summary="关注 terminal event 与 sequence 连续性。",
        target_sources=[ResearchSourceTarget.PAPER],
        confirmation_required=False,
    )

    await service.execute_session(session=session, plan_snapshot=plan_snapshot)

    envelopes = service.list_event_envelopes(session)
    replay_state = replay_research_session(envelopes)
    consistency = evaluate_research_replay_consistency(
        session=session,
        events=envelopes,
    )

    assert replay_state.status == ResearchSessionStatus.FINAL
    assert replay_state.last_sequence == session.last_event_sequence
    assert replay_state.last_event_id == envelopes[-1].event_id
    assert replay_state.sequence_gaps == []
    assert consistency["pass"] is True
    assert consistency["replay_status"] == ResearchSessionStatus.FINAL.value


def test_replay_detects_sequence_gaps() -> None:
    session_id = uuid4()
    envelopes = [
        ResearchEventEnvelope(
            event_id="evt-001",
            sequence=1,
            timestamp="2026-03-30T00:00:00Z",
            event_type="research.plan.created",
            session_id=session_id,
            phase="planner",
            namespace="main",
            payload={"lc_agent_name": "planner"},
            trace_id="trace-gap",
            lc_agent_name="planner",
        ),
        ResearchEventEnvelope(
            event_id="evt-003",
            sequence=3,
            timestamp="2026-03-30T00:01:00Z",
            event_type="research.run.started",
            session_id=session_id,
            phase="runtime",
            namespace="main",
            payload={"lc_agent_name": "deep-research"},
            trace_id="trace-gap",
            lc_agent_name="deep-research",
        ),
    ]

    replay_state = replay_research_session(envelopes)

    assert replay_state.sequence_gaps == [2]
    assert replay_state.status == ResearchSessionStatus.RUNNING

