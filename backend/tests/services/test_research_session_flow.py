from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from app.models.research_session import ResearchSessionStatus
from app.schemas.research import (
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionAccepted,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_service import ResearchService


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class _StaticPlanner:
    def __init__(self, result: ResearchPlannerResult) -> None:
        self._result = result

    async def build_plan(self, request: ResearchSessionCreateRequest) -> ResearchPlannerResult:
        assert request.question.strip()
        return self._result


class _DummyRuntimeRunner:
    async def run_session(self, *, session, plan_snapshot):  # pragma: no cover - not used here
        raise AssertionError("runtime should not be used in planning flow tests")


class _DummyFinalizer:
    def finalize(self, *, question, target_sources, source_bundle):  # pragma: no cover - not used here
        raise AssertionError("finalizer should not be used in planning flow tests")


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="比较当前 RAG 领域的最新进展，并按检索器、索引、融合策略与实验结果输出报告。",
        complexity="comparative",
        summary="先按主题拆解研究步骤，确认范围后再启动执行。",
        subtasks=[
            ResearchPlanSubtask(
                title="检索近两年顶会论文",
                description="整理顶会与期刊中的代表性论文。",
                target_sources=[ResearchSourceTarget.PAPER],
            ),
            ResearchPlanSubtask(
                title="汇总工业界实践",
                description="补充主要公司和开源项目的公开技术说明。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
        ],
        target_sources=[ResearchSourceTarget.PAPER, ResearchSourceTarget.WEB],
        budget_guidance="优先官方、原始和可复核来源。",
    )


def _build_service(*, planner_result: ResearchPlannerResult) -> ResearchService:
    return ResearchService(
        db=_FakeAsyncSession(),  # type: ignore[arg-type]
        planner=_StaticPlanner(planner_result),  # type: ignore[arg-type]
        runtime_runner=_DummyRuntimeRunner(),
        finalizer=_DummyFinalizer(),  # type: ignore[arg-type]
    )


def test_research_session_accepted_requires_plan_snapshot_for_plan_ready() -> None:
    accepted = ResearchSessionAccepted(
        session_id=uuid.uuid4(),
        status=ResearchSessionStatus.PLAN_READY,
        plan_snapshot=_build_plan_snapshot(),
        clarification_request=None,
    )

    assert accepted.status == ResearchSessionStatus.PLAN_READY
    assert accepted.plan_snapshot is not None


@pytest.mark.asyncio
async def test_create_session_stops_at_plan_ready_instead_of_auto_queueing() -> None:
    service = _build_service(
        planner_result=ResearchPlannerResult(
            plan_snapshot=_build_plan_snapshot(),
            clarification_request=None,
            auto_approve=False,
            next_status=ResearchSessionStatus.PLAN_READY,
        )
    )

    session, result = await service.create_session(
        ResearchSessionCreateRequest(question="当前 RAG 领域的最新进展"),
        session_id=uuid.uuid4(),
        thread_id="thread-plan-ready",
    )

    assert session.status == ResearchSessionStatus.PLAN_READY
    assert result.plan_snapshot is not None


@pytest.mark.asyncio
async def test_service_exposes_explicit_start_and_stop_entrypoints() -> None:
    service = _build_service(
        planner_result=ResearchPlannerResult(
            plan_snapshot=_build_plan_snapshot(),
            clarification_request=None,
            auto_approve=False,
            next_status=ResearchSessionStatus.PLAN_READY,
        )
    )
    session, _ = await service.create_session(
        ResearchSessionCreateRequest(question="当前 RAG 领域的最新进展"),
        session_id=uuid.uuid4(),
        thread_id="thread-start-stop",
    )

    started = await service.start_session(session=session)
    assert started.status == ResearchSessionStatus.QUEUED

    stopped = await service.stop_session(session=started, reason="用户停止本次研究")
    assert stopped.status == ResearchSessionStatus.CANCELED


@pytest.mark.asyncio
async def test_stop_running_session_hard_cuts_to_canceled() -> None:
    service = _build_service(
        planner_result=ResearchPlannerResult(
            plan_snapshot=_build_plan_snapshot(),
            clarification_request=None,
            auto_approve=False,
            next_status=ResearchSessionStatus.PLAN_READY,
        )
    )
    session, _ = await service.create_session(
        ResearchSessionCreateRequest(question="当前 RAG 领域的最新进展"),
        session_id=uuid.uuid4(),
        thread_id="thread-stop-running",
    )

    session = await service.start_session(session=session)
    session.transition_to(ResearchSessionStatus.RUNNING)

    stopped = await service.stop_session(session=session, reason="用户主动停止")

    assert stopped.status == ResearchSessionStatus.CANCELED
