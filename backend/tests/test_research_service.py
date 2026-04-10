from __future__ import annotations

from contextlib import nullcontext
import uuid

import pytest

from app.models.research_artifact import ResearchArtifact
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_finalizer import ResearchFinalizerResult
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_runtime_types import ResearchPlanProgressUpdate
from app.services.research_service import ResearchService
from app.services.research_source_bundle import ResearchSourceBundle


class _FakeDb:
    def __init__(
        self,
        *,
        committed_status: ResearchSessionStatus | None = None,
    ) -> None:
        self.committed_status = committed_status
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)

    @property
    def no_autoflush(self):
        return nullcontext()

    async def scalar(self, stmt: object) -> ResearchSessionStatus | None:
        del stmt
        return self.committed_status


class _FakePlanner:
    async def build_plan(self, request: object) -> object:
        del request
        raise AssertionError("test should not invoke planner")


class _FakeRuntimeRunner:
    def __init__(
        self,
        runtime_result: ResearchRuntimeRunResult,
        *,
        progress_updates: list[ResearchPlanProgressUpdate] | None = None,
    ) -> None:
        self._runtime_result = runtime_result
        self._progress_updates = list(progress_updates or [])

    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        plan_progress_callback=None,
    ) -> ResearchRuntimeRunResult:
        del session, plan_snapshot
        if plan_progress_callback is not None:
            for update in self._progress_updates:
                await plan_progress_callback(update)
        return self._runtime_result


class _SpyFinalizer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def finalize(
        self,
        *,
        question: str,
        target_sources: list[ResearchSourceTarget],
        source_bundle: ResearchSourceBundle,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None = None,
    ) -> ResearchFinalizerResult:
        self.calls.append(
            {
                "question": question,
                "target_sources": list(target_sources),
                "source_bundle": source_bundle,
                "runtime_context_snapshot": runtime_context_snapshot,
            }
        )
        return ResearchFinalizerResult(
            report_md="# 最终报告",
            report_json={
                "summary": source_bundle.interim_summary,
                "findings": list(source_bundle.findings),
                "claim_map": {"claims": []},
                "coverage_matrix": {"pass": True},
                "conflicts": [],
                "source_ledger": [],
            },
        )


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="验证运行中取消后的收口行为",
        complexity=ResearchComplexity.SIMPLE,
        summary="围绕取消链路做最小验证",
        subtasks=[
            {
                "title": "收集关键事实",
                "description": "收集研究问题对应的第一批高置信事实。",
                "target_sources": [ResearchSourceTarget.WEB],
            },
            {
                "title": "整理结论草稿",
                "description": "基于证据收敛阶段性结论。",
                "target_sources": [ResearchSourceTarget.WEB],
            },
        ],
        target_sources=[ResearchSourceTarget.WEB],
    )


def _build_runtime_result() -> ResearchRuntimeRunResult:
    citation = ResearchCanonicalCitation(
        source_type=ResearchSourceType.WEB,
        source_provider="tavily",
        retrieval_method="search",
        source_id="src-1",
        title="示例来源",
        origin_url="https://example.com/research",
    )
    source_bundle = ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[citation],
        findings=["已拿到一条可追溯证据"],
        interim_summary="已收集到部分研究证据。",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )
    return ResearchRuntimeRunResult(
        source_bundle=source_bundle,
        latency_ms=250,
        quality_score=0.92,
    )


def _build_runtime_result_with_context() -> ResearchRuntimeRunResult:
    runtime_result = _build_runtime_result()
    return ResearchRuntimeRunResult(
        source_bundle=runtime_result.source_bundle,
        runtime_context_snapshot=ResearchRuntimeContextSnapshot(
            claim_map_md="# 核心主张\n- Claim A",
            evidence_ledger_md="# 证据账本\n- [1] Evidence",
            analysis_notes_md="# 中间分析\n- Note",
            report_outline_md="# 报告提纲\n- 核心结论",
            report_draft_md="# 报告草稿\n- Draft",
            report_context_json={"executive_summary": "summary"},
            files_snapshot={"/workspace/research/session-123/05-claim-map.md": "# 核心主张"},
        ),
        latency_ms=runtime_result.latency_ms,
        quality_score=runtime_result.quality_score,
    )


def _build_session() -> ResearchSession:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id=f"thread-{uuid.uuid4()}",
        question="研究取消后是否仍会继续生成报告",
        status=ResearchSessionStatus.QUEUED,
    )
    session.events = []
    session.artifacts = []
    session.task_outbox_entries = []
    session.last_event_sequence = 0
    return session


def _attach_plan_snapshot_artifact(
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot | None = None,
) -> ResearchPlanSnapshot:
    resolved_snapshot = plan_snapshot or _build_plan_snapshot()
    session.artifacts.append(
        ResearchArtifact(
            session_id=session.id,
            artifact_key="plan_snapshot",
            content_json=resolved_snapshot.model_dump(mode="json"),
        )
    )
    return resolved_snapshot


def _build_service(
    *,
    db: _FakeDb,
    runtime_result: ResearchRuntimeRunResult | None = None,
    runtime_runner: _FakeRuntimeRunner | None = None,
    finalizer: _SpyFinalizer | None = None,
) -> tuple[ResearchService, _SpyFinalizer]:
    resolved_finalizer = finalizer or _SpyFinalizer()
    service = ResearchService(
        db=db,  # type: ignore[arg-type]
        planner=_FakePlanner(),  # type: ignore[arg-type]
        runtime_runner=runtime_runner
        or _FakeRuntimeRunner(runtime_result or _build_runtime_result()),
        finalizer=resolved_finalizer,  # type: ignore[arg-type]
    )
    return service, resolved_finalizer


@pytest.mark.asyncio
async def test_execute_session_skips_finalizer_when_committed_status_is_canceled() -> None:
    db = _FakeDb(committed_status=ResearchSessionStatus.CANCELED)
    service, finalizer = _build_service(db=db)
    session = _build_session()

    result = await service.execute_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    assert result is None
    assert finalizer.calls == []
    assert session.status == ResearchSessionStatus.CANCELED
    assert session.finished_at is not None

    artifact_keys = {artifact.artifact_key for artifact in session.artifacts}
    assert {
        "source_bundle",
        "interim_findings",
        "interim_summary",
        "coverage_gaps",
    }.issubset(artifact_keys)
    assert "report_json" not in artifact_keys
    assert "report_md" not in artifact_keys

    event_types = [event.event_type for event in session.events]
    assert "research.run.started" in event_types
    assert "research.finalizer.started" not in event_types
    assert "research.final.completed" not in event_types


@pytest.mark.asyncio
async def test_start_session_initializes_plan_progress_snapshot() -> None:
    db = _FakeDb()
    service, _ = _build_service(db=db)
    session = _build_session()
    session.status = ResearchSessionStatus.PLAN_READY
    plan_snapshot = _attach_plan_snapshot_artifact(session)

    result = await service.start_session(session=session)

    assert result.status == ResearchSessionStatus.QUEUED
    plan_progress_artifact = next(
        artifact
        for artifact in session.artifacts
        if artifact.artifact_key == "plan_progress_snapshot"
    )
    assert plan_progress_artifact.content_json == {
        "steps": [
            {
                "index": 1,
                "title": plan_snapshot.subtasks[0].title,
                "description": plan_snapshot.subtasks[0].description,
                "target_sources": ["web"],
                "status": "current",
            },
            {
                "index": 2,
                "title": plan_snapshot.subtasks[1].title,
                "description": plan_snapshot.subtasks[1].description,
                "target_sources": ["web"],
                "status": "pending",
            },
        ],
        "current_step_index": 1,
        "completed_step_count": 0,
        "updated_at": plan_progress_artifact.content_json["updated_at"],
    }
    assert [
        event.event_type for event in session.events[-2:]
    ] == ["research.run.queued", "research.plan_progress.updated"]


@pytest.mark.asyncio
async def test_execute_session_marks_plan_progress_complete_before_finalizer() -> None:
    db = _FakeDb(committed_status=ResearchSessionStatus.RUNNING)
    service, _ = _build_service(db=db)
    session = _build_session()
    plan_snapshot = _build_plan_snapshot()

    await service.execute_session(
        session=session,
        plan_snapshot=plan_snapshot,
    )

    plan_progress_artifact = next(
        artifact
        for artifact in session.artifacts
        if artifact.artifact_key == "plan_progress_snapshot"
    )
    assert plan_progress_artifact.content_json == {
        "steps": [
            {
                "index": 1,
                "title": plan_snapshot.subtasks[0].title,
                "description": plan_snapshot.subtasks[0].description,
                "target_sources": ["web"],
                "status": "complete",
            },
            {
                "index": 2,
                "title": plan_snapshot.subtasks[1].title,
                "description": plan_snapshot.subtasks[1].description,
                "target_sources": ["web"],
                "status": "complete",
            },
        ],
        "current_step_index": None,
        "completed_step_count": 2,
        "updated_at": plan_progress_artifact.content_json["updated_at"],
    }
    assert "research.plan_progress.updated" in [event.event_type for event in session.events]


@pytest.mark.asyncio
async def test_execute_session_persists_runtime_plan_progress_updates() -> None:
    db = _FakeDb(committed_status=ResearchSessionStatus.RUNNING)
    runtime_runner = _FakeRuntimeRunner(
        _build_runtime_result(),
        progress_updates=[
            ResearchPlanProgressUpdate(
                step_index=1,
                status="complete",
                message="第一步事实收集已完成",
            )
        ],
    )
    service, _ = _build_service(db=db, runtime_runner=runtime_runner)
    session = _build_session()
    plan_snapshot = _build_plan_snapshot()

    await service.execute_session(
        session=session,
        plan_snapshot=plan_snapshot,
    )

    matching_event = next(
        event
        for event in session.events
        if event.event_type == "research.plan_progress.updated"
        and event.phase == "runtime"
        and event.payload.get("completed_step_count") == 1
        and event.payload.get("current_step_index") == 2
    )
    steps = matching_event.payload.get("steps")
    assert isinstance(steps, list)
    assert steps[0]["status"] == "complete"
    assert steps[1]["status"] == "current"


@pytest.mark.asyncio
async def test_execute_session_keeps_finalizer_path_when_not_canceled() -> None:
    db = _FakeDb(committed_status=ResearchSessionStatus.RUNNING)
    service, finalizer = _build_service(db=db)
    session = _build_session()

    result = await service.execute_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    assert result is not None
    assert len(finalizer.calls) == 1
    assert session.status == ResearchSessionStatus.FINAL
    assert session.finished_at is not None

    artifact_keys = {artifact.artifact_key for artifact in session.artifacts}
    assert {
        "report_json",
        "report_md",
        "claim_map_json",
        "coverage_matrix_json",
        "conflicts_json",
        "source_ledger_json",
    }.issubset(artifact_keys)


@pytest.mark.asyncio
async def test_execute_session_persists_runtime_context_artifacts() -> None:
    runtime_result = _build_runtime_result_with_context()
    db = _FakeDb(committed_status=ResearchSessionStatus.RUNNING)
    service, finalizer = _build_service(db=db, runtime_result=runtime_result)
    session = _build_session()

    result = await service.execute_session(
        session=session,
        plan_snapshot=_build_plan_snapshot(),
    )

    assert result is not None
    artifact_keys = {artifact.artifact_key for artifact in session.artifacts}
    assert {
        "runtime_claim_map_md",
        "runtime_evidence_ledger_md",
        "runtime_analysis_notes_md",
        "runtime_report_outline_md",
        "runtime_report_draft_md",
        "runtime_report_context_json",
        "runtime_files_snapshot_json",
    }.issubset(artifact_keys)
    assert finalizer.calls[0]["runtime_context_snapshot"] is not None
