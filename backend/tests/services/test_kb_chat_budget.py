from __future__ import annotations

import math
from types import SimpleNamespace

from app.agents.kb_chat_agentic.budget import (
    budget_exceeded,
    effective_timeout_seconds,
    ensure_budget_initialized,
    remaining_budget_seconds,
)


def _settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        kb_chat_total_timeout_seconds=45.0,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
        kb_chat_max_generation_retries=1,
    )


def test_ensure_budget_initialized_does_not_attach_deadline() -> None:
    settings = _settings_stub()
    updates = ensure_budget_initialized({"metrics": {}}, settings)

    budget = updates["metrics"]["budget"]
    assert "deadline_ts" not in budget
    assert isinstance(budget.get("started_at"), str) and budget["started_at"]


def test_budget_exceeded_ignores_deadline_field() -> None:
    settings = _settings_stub()
    exceeded, reason = budget_exceeded(
        {
            "metrics": {"budget": {"deadline_ts": 0}},
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
        },
        settings,
    )

    assert exceeded is False
    assert reason == ""


def test_remaining_budget_seconds_is_unbounded_without_total_timeout() -> None:
    settings = _settings_stub()
    remaining = remaining_budget_seconds({"metrics": {"budget": {}}}, settings)

    assert math.isinf(remaining)


def test_effective_timeout_seconds_returns_none_for_unbounded_budget() -> None:
    assert effective_timeout_seconds(None, float("inf")) is None


def test_effective_timeout_seconds_still_clamps_when_component_has_timeout() -> None:
    assert effective_timeout_seconds(30.0, 10.0) == 10.0
