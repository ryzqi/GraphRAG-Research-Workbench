from __future__ import annotations

from uuid import uuid4

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchCanonicalCitation,
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
from app.services.research_replay import evaluate_research_replay_consistency
from app.services.research_service import ResearchService
from app.services.research_source_bundle import ResearchSourceBundleBuilder


class _FakeAsyncSession:
    def add(self, obj: object) -> None:
        del obj


class _ResumeAwareRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        finding_prefix = (
            "恢复后继续执行"
            if session.status == ResearchSessionStatus.RESUMING
            else "首次执行"
        )
        citation = ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="jina_reader",
            retrieval_method="read",
            source_id="https://r.jina.ai/http://example.com/resume",
            title="Interrupt Resume Contract",
            url="https://r.jina.ai/http://example.com/resume",
            origin_url="https://example.com/resume",
        )
        bundle = ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=[citation],
            findings=[f"{finding_prefix}，最终进入 final。", "resume 请求保持幂等。"],
            required_web_providers=("jina_reader",),
        )
        return ResearchRuntimeRunResult(
            source_bundle=bundle,
            trace_links=(
                ResearchTraceLink(lc_agent_name="deep-research", namespace="main"),
                ResearchTraceLink(lc_agent_name="web", namespace="research/web"),
            ),
            latency_ms=2_400,
            total_cost_usd=0.88,
        )


async def test_interrupt_resume_contract_reaches_final_with_consistent_replay() -> None:
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(),
        runtime_runner=_ResumeAwareRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        id=uuid4(),
        thread_id="research-interrupt-resume-session",
        question="验证 interrupt -> resume -> final 契约",
        status=ResearchSessionStatus.AWAITING_CONFIRMATION,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="验证中断恢复闭环。",
        complexity="comparative",
        summary="确认 -> interrupt -> resume -> final。",
        target_sources=[ResearchSourceTarget.WEB],
        confirmation_required=True,
    )

    await service.confirm_plan(session=session, approved=True, note="继续执行")
    session.status = ResearchSessionStatus.RUNNING
    await service.interrupt_session(session=session, reason="等待人工确认")
    interrupt_event_id = session.events[-1].event_id

    resume_response = await service.resume_session(
        session=session,
        idempotency_key="resume-contract-1",
        resume_from_event_id=interrupt_event_id,
        decisions=[{"action": "approve", "scope": "research"}],
    )
    await service.execute_session(session=session, plan_snapshot=plan_snapshot)

    envelopes = service.list_event_envelopes(session)
    consistency = evaluate_research_replay_consistency(session=session, events=envelopes)

    assert resume_response == {
        "status": "accepted",
        "resume_from_event_id": interrupt_event_id,
        "decision_count": 1,
    }
    assert session.status == ResearchSessionStatus.FINAL
    assert consistency["pass"] is True
    assert any(item.event_type == "research.run.interrupted" for item in envelopes)
    assert any(item.event_type == "research.run.resume_requested" for item in envelopes)
    assert envelopes[-1].event_type == "research.final.completed"
    assert (session.metrics or {})["gate"]["pass"] is True
