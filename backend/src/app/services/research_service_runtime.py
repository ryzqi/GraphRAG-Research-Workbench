from __future__ import annotations

from typing import Protocol

from app.models.research_session import ResearchSession
from app.schemas.research import ResearchPlanSnapshot
from app.services.research_observability import ResearchRuntimeRunResult


class ResearchRuntimeRunner(Protocol):
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        runtime_activity_callback=None,
    ) -> ResearchRuntimeRunResult: ...


class UnconfiguredResearchRuntimeRunner:
    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        runtime_activity_callback=None,
    ) -> ResearchRuntimeRunResult:
        del session, plan_snapshot, runtime_activity_callback
        raise RuntimeError("Research runtime runner 未配置")
