"""Preflight planner 类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.research_session import ResearchSessionStatus
from app.schemas.research import ResearchPlanSnapshot


PLAN_SNAPSHOT_ARTIFACT_KEY = "plan_snapshot"


@dataclass(slots=True, frozen=True)
class ResearchPlannerResult:
    plan_snapshot: ResearchPlanSnapshot
    auto_approve: bool
    next_status: ResearchSessionStatus
    plan_artifact_key: str = PLAN_SNAPSHOT_ARTIFACT_KEY

    @property
    def artifact_payload(self) -> dict[str, Any]:
        return self.plan_snapshot.model_dump(mode="json")
