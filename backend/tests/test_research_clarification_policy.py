from __future__ import annotations

from types import SimpleNamespace

from app.services.research_service import ResearchService


def test_submitted_research_clarification_forces_planner_to_proceed() -> None:
    session = SimpleNamespace(events=[])

    allow_clarify = ResearchService._should_allow_follow_up_clarification(
        session=session,
        answer="最近指 2025-2026 年，重点关注架构、评估和工程落地。",
    )

    assert allow_clarify is False

