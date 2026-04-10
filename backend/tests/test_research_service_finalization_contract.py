from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.research_artifact import ResearchArtifact
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_finalizer import ResearchFinalizerResult
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_service import ResearchService
from app.services.research_source_bundle import ResearchSourceBundle


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot.model_validate(
        {
            "research_brief": "验证 final 发布顺序。",
            "complexity": "simple",
            "summary": "先写报告，再写 metrics/gate，最后发布 final。",
            "subtasks": [
                {
                    "title": "收口报告",
                    "description": "完成报告与指标落库。",
                    "target_sources": ["web"],
                }
            ],
            "target_sources": ["web"],
        }
    )


def _build_source_bundle() -> ResearchSourceBundle:
    return ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[
            ResearchCanonicalCitation(
                source_type=ResearchSourceType.WEB,
                source_provider="tavily",
                retrieval_method="web_search",
                source_id="https://example.com/final",
                title="Final Contract",
                url="https://example.com/final",
                origin_url="https://example.com/final",
            )
        ],
        findings=["结论 A", "结论 B"],
        interim_summary="已汇总最终结论。",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )


class _FakeDb:
    def add(self, obj: object) -> None:
        del obj

    async def commit(self) -> None:
        return None


class _FakeArtifactStore:
    def __init__(self, call_log: list[str]) -> None:
        self.calls: list[str] = []
        self._call_log = call_log

    async def upsert(
        self,
        *,
        session: ResearchSession,
        artifact_key: str,
        content_text: str | None = None,
        content_json: dict | list | None = None,
        source_type: str | None = None,
        source_provider: str | None = None,
        retrieval_method: str | None = None,
        origin_url: str | None = None,
    ) -> ResearchArtifact:
        self.calls.append(artifact_key)
        self._call_log.append(f"artifact:{artifact_key}")
        existing = next(
            (item for item in session.artifacts if item.artifact_key == artifact_key),
            None,
        )
        if existing is None:
            existing = ResearchArtifact(artifact_key=artifact_key)
            existing.session = session
            session.artifacts.append(existing)
        existing.content_text = content_text
        existing.content_json = content_json
        existing.source_type = source_type
        existing.source_provider = source_provider
        existing.retrieval_method = retrieval_method
        existing.origin_url = origin_url
        return existing


class _FakeEventStore:
    def __init__(self, call_log: list[str]) -> None:
        self.calls: list[str] = []
        self._call_log = call_log

    async def append(
        self,
        *,
        session: ResearchSession,
        event_type: str,
        phase: str,
        payload: dict,
        trace_id: str | None,
        namespace: str = "main",
        source_provider: str | None = None,
        retrieval_method: str | None = None,
        origin_url: str | None = None,
        lc_agent_name: str | None = None,
        subagent_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResearchEvent:
        del source_provider, retrieval_method, origin_url, lc_agent_name, subagent_name, idempotency_key
        self.calls.append(event_type)
        self._call_log.append(f"event:{event_type}")
        event = ResearchEvent(
            session_id=session.id,
            event_id=f"evt-{len(session.events) + 1}",
            sequence=len(session.events) + 1,
            event_type=event_type,
            phase=phase,
            namespace=namespace,
            payload=payload,
            trace_id=trace_id,
        )
        event.created_at = datetime.now(timezone.utc)
        event.session = session
        session.events.append(event)
        session.last_event_sequence = event.sequence
        return event


@dataclass
class _FakeRuntimeRunner:
    result: ResearchRuntimeRunResult

    async def run_session(self, **_: object) -> ResearchRuntimeRunResult:
        return self.result


@dataclass
class _FakeFinalizer:
    result: ResearchFinalizerResult

    def finalize(self, **_: object) -> ResearchFinalizerResult:
        return self.result


def test_execute_session_persists_metrics_before_final_event(monkeypatch) -> None:
    call_log: list[str] = []
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="如何验证 final 顺序？",
        status=ResearchSessionStatus.QUEUED,
    )
    session.artifacts = []
    session.events = []
    session.task_outbox_entries = []

    source_bundle = _build_source_bundle()
    service = object.__new__(ResearchService)
    service._db = _FakeDb()
    service._artifact_store = _FakeArtifactStore(call_log)
    service._event_store = _FakeEventStore(call_log)
    service._runtime_runner = _FakeRuntimeRunner(
        ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            runtime_context_snapshot=ResearchRuntimeContextSnapshot(
                report_context_json={"executive_summary": "最终摘要"},
                task_graph_json={"tasks": [{"title": "收口报告"}]},
                claim_bundles_json=[{"claim_id": "claim-1"}],
                section_briefs_json=[{"section_id": "section-1"}],
                live_board_json={"recent_activity": [{"task_id": "claim-1"}]},
                todos_json=[{"content": "todo"}],
            ),
        )
    )
    service._finalizer = _FakeFinalizer(
        ResearchFinalizerResult(
            report_md="# 研究报告\n\n## 摘要\n内容",
            report_json={
                "question": session.question,
                "target_sources": ["web"],
                "summary": "最终摘要",
                "findings": ["结论 A", "结论 B"],
                "coverage_gaps": [],
                "provider_counts": {"tavily": 1},
                "citations": [
                    {
                        "source_type": "web",
                        "source_provider": "tavily",
                        "retrieval_method": "web_search",
                        "source_id": "https://example.com/final",
                        "title": "Final Contract",
                        "url": "https://example.com/final",
                        "origin_url": "https://example.com/final",
                        "authors": [],
                    }
                ],
                "sections": [{"title": "摘要", "content": "内容"}],
                "metadata": {
                    "confidence_level": "partial",
                    "evidence_count": 1,
                    "has_conflicts": False,
                    "generated_at": "2026-04-10T00:00:00Z",
                },
                "claim_map": [],
                "coverage_matrix": {"provider_counts": {"tavily": 1}, "missing_providers": []},
                "conflicts": [],
                "source_ledger": [],
            },
        )
    )
    service._settings = None
    service._gate_thresholds = object()

    async def _noop_persist_runtime_context_artifacts(**_: object) -> None:
        return None

    async def _noop_commit_checkpoint() -> None:
        return None

    async def _no_committed_status(*, session: ResearchSession) -> ResearchSessionStatus | None:
        del session
        return None

    service._persist_runtime_context_artifacts = _noop_persist_runtime_context_artifacts
    service._commit_checkpoint = _noop_commit_checkpoint
    service._read_committed_session_status = _no_committed_status

    monkeypatch.setattr(
        "app.services.research_service.build_research_metrics",
        lambda **_: {"quality": {"citation_count": 1, "finding_count": 2}},
    )
    monkeypatch.setattr(
        "app.services.research_service.evaluate_research_replay_consistency",
        lambda **_: {"pass": True},
    )
    monkeypatch.setattr(
        "app.services.research_service.evaluate_research_gate",
        lambda **_: {"pass": True},
    )

    result = asyncio.run(
        service.execute_session(session=session, plan_snapshot=_build_plan_snapshot())
    )
    report_json_artifact = next(
        item for item in session.artifacts if item.artifact_key == "report_json"
    )

    assert result is not None
    assert session.status == ResearchSessionStatus.FINAL
    assert call_log.index("artifact:metrics_snapshot") < call_log.index(
        "event:research.final.completed"
    )
    assert call_log.index("artifact:gate_snapshot") < call_log.index(
        "event:research.final.completed"
    )
    assert isinstance(report_json_artifact.content_json, dict)
    assert "task_graph" not in report_json_artifact.content_json
    assert "live_board" not in report_json_artifact.content_json
    assert "claim_bundles" not in report_json_artifact.content_json
    assert "section_briefs" not in report_json_artifact.content_json
