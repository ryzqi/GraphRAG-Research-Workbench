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
    ResearchGateThresholds,
    ResearchModelStat,
    ResearchProviderStat,
    ResearchRuntimeRunResult,
    ResearchTraceLink,
    build_research_metrics,
    evaluate_research_gate,
)
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


class _ObservableRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        citation = ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="tavily",
            retrieval_method="search",
            source_id="https://example.com/deep-research-observability",
            title="Deep Research Observability",
            url="https://example.com/deep-research-observability",
            origin_url="https://example.com/deep-research-observability",
        )
        source_bundle = ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=[citation],
            findings=[
                f"已为会话 {session.thread_id} 收集 observability 所需网页证据。",
                "trace / metrics / gate 已具备最小闭环。",
            ],
            required_web_providers=("tavily",),
        )
        return ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            trace_links=(
                ResearchTraceLink(
                    lc_agent_name="deep-research",
                    namespace="main",
                ),
                ResearchTraceLink(
                    lc_agent_name="web",
                    namespace="research/web",
                    source_provider="tavily",
                ),
            ),
            provider_stats=(
                ResearchProviderStat(
                    source_provider="tavily",
                    channel="web",
                    latency_ms=1_250,
                    success=True,
                ),
            ),
            model_stats=(
                ResearchModelStat(
                    layer="primary",
                    model="gpt-5.2",
                    lc_agent_name="deep-research",
                    namespace="main",
                    cost_usd=0.78,
                ),
                ResearchModelStat(
                    layer="subagent",
                    model="gpt-5.2-mini",
                    lc_agent_name="web",
                    namespace="research/web",
                    cost_usd=0.14,
                ),
            ),
            latency_ms=1_850,
            total_cost_usd=0.92,
        )


async def test_execute_session_persists_trace_metrics_gate_and_trace_events() -> None:
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(),
        runtime_runner=_ObservableRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        id=uuid4(),
        thread_id="research-observability-session",
        question="为 Deep Research 打通 tracing / metrics / gate",
        status=ResearchSessionStatus.QUEUED,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="围绕 tracing / metrics / gate 打通 observability。",
        complexity="comparative",
        summary="先跑网页来源，再汇总门禁。",
        target_sources=[ResearchSourceTarget.WEB],
    )

    await service.execute_session(
        session=session,
        plan_snapshot=plan_snapshot,
    )

    metrics = session.metrics or {}
    assert session.trace_id is not None
    assert metrics["trace"]["session_id"] == str(session.id)
    assert metrics["trace"]["trace_id"] == session.trace_id
    assert metrics["quality"]["score"] >= 0.75
    assert metrics["latency"]["p95_ms"] == 1_850
    assert metrics["cost"]["session_cost_usd"] == 0.92
    assert metrics["providers"]["by_source_provider"]["tavily"]["count"] == 1
    assert metrics["models"]["by_lc_agent_name"]["web"]["cost_usd"] == 0.14
    assert metrics["gate"]["pass"] is False
    assert "coverage" in metrics["gate"]["violations"]
    assert metrics["replay"]["pass"] is True

    artifact_keys = [artifact.artifact_key for artifact in session.artifacts]
    assert "metrics_snapshot" in artifact_keys
    assert "gate_snapshot" in artifact_keys

    envelopes = service.list_event_envelopes(session)
    assert any(item.event_type == "research.trace.recorded" for item in envelopes)
    assert any(item.lc_agent_name == "deep-research" for item in envelopes)
    assert any(
        item.event_type == "research.trace.recorded"
        and item.namespace == "research/web"
        and item.lc_agent_name == "web"
        for item in envelopes
    )


def test_build_research_metrics_marks_coverage_gate_and_forces_gate_failure() -> None:
    session = ResearchSession(
        id=uuid4(),
        thread_id="coverage-gate-session",
        question="比较多 provider 的 deep research coverage",
        status=ResearchSessionStatus.RUNNING,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="比较多 provider 的 deep research coverage。",
        complexity="comparative",
        summary="检查 provider coverage gate 是否进入真实 metrics/gate。",
        target_sources=[ResearchSourceTarget.WEB],
    )
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="tavily",
            retrieval_method="search",
            source_id=f"https://example.com/source-{index}",
            title=f"Source {index}",
            url=f"https://example.com/source-{index}",
            origin_url=f"https://example.com/source-{index}",
        )
        for index in range(8)
    ]
    source_bundle = ResearchSourceBundleBuilder().build(
        target_sources=plan_snapshot.target_sources,
        citations=citations,
        findings=[
            "比较型研究应覆盖多个 web providers。",
            "provider shortage 不能被质量分旁路掩盖。",
        ],
        required_web_providers=("tavily", "jina_reader", "searxng"),
    )
    runtime_result = ResearchRuntimeRunResult(
        source_bundle=source_bundle,
        latency_ms=1_000,
        total_cost_usd=0.1,
        quality_score=0.95,
    )

    metrics = build_research_metrics(
        session=session,
        plan_snapshot=plan_snapshot,
        runtime_result=runtime_result,
    )
    gate = evaluate_research_gate(
        metrics={**metrics, "replay": {"pass": True}},
        thresholds=ResearchGateThresholds(),
    )

    assert metrics["coverage"]["pass"] is False
    assert "missing_web_provider_count" in metrics["coverage"]["reasons"]
    assert gate["pass"] is False
    assert "coverage" in gate["violations"]


def test_build_research_metrics_allows_paper_only_complex_plan() -> None:
    session = ResearchSession(
        id=uuid4(),
        thread_id="paper-only-session",
        question="整理论文研究基线",
        status=ResearchSessionStatus.RUNNING,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="只做论文来源研究。",
        complexity="complex",
        summary="paper-only 不应要求 web provider coverage。",
        target_sources=[ResearchSourceTarget.PAPER],
    )
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.PAPER,
            source_provider="arxiv",
            retrieval_method="fetch",
            source_id=f"arxiv:2501.{index:05d}",
            title=f"Paper {index}",
            url=f"https://arxiv.org/abs/2501.{index:05d}",
            origin_url=f"https://arxiv.org/abs/2501.{index:05d}",
            arxiv_id=f"2501.{index:05d}",
            pdf_url=f"https://arxiv.org/pdf/2501.{index:05d}.pdf",
        )
        for index in range(12)
    ]
    source_bundle = ResearchSourceBundleBuilder().build(
        target_sources=plan_snapshot.target_sources,
        citations=citations,
        findings=["论文基线一。", "论文基线二。"],
        required_web_providers=(),
    )
    metrics = build_research_metrics(
        session=session,
        plan_snapshot=plan_snapshot,
        runtime_result=ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            latency_ms=1000,
            total_cost_usd=0.1,
            quality_score=0.95,
        ),
    )
    gate = evaluate_research_gate(
        metrics={**metrics, "replay": {"pass": True}},
        thresholds=ResearchGateThresholds(),
    )

    assert metrics["coverage"]["pass"] is True
    assert gate["pass"] is True


def test_build_research_metrics_allows_workspace_only_web_path_when_evidence_is_sufficient() -> None:
    session = ResearchSession(
        id=uuid4(),
        thread_id="workspace-web-session",
        question="概述当前 Deep Research session contract",
        status=ResearchSessionStatus.RUNNING,
    )
    plan_snapshot = ResearchPlanSnapshot(
        research_brief="仅基于 workspace 文档回答当前 contract 问题。",
        complexity="simple",
        summary="workspace 文档足够时不应强制外部 web provider。",
        target_sources=[ResearchSourceTarget.WEB],
    )
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="workspace",
            retrieval_method="read_file",
            source_id=f"/workspace/context/doc-{index}.md",
            title=f"Doc {index}",
            url=f"file:///workspace/context/doc-{index}.md",
            origin_url=f"file:///workspace/context/doc-{index}.md",
        )
        for index in range(5)
    ]
    source_bundle = ResearchSourceBundleBuilder().build(
        target_sources=plan_snapshot.target_sources,
        citations=citations,
        findings=["workspace 证据一。", "workspace 证据二。"],
        required_web_providers=(),
    )
    metrics = build_research_metrics(
        session=session,
        plan_snapshot=plan_snapshot,
        runtime_result=ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            latency_ms=800,
            total_cost_usd=0.0,
            quality_score=0.9,
        ),
    )
    gate = evaluate_research_gate(
        metrics={**metrics, "replay": {"pass": True}},
        thresholds=ResearchGateThresholds(),
    )

    assert metrics["coverage"]["pass"] is True
    assert metrics["coverage"]["reasons"] == []
    assert gate["pass"] is True
