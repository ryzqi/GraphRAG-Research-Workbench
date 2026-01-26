"""KB Chat budgets (timeout/rounds/retries) for agentic graph.

Design notes:
- Budgets must be checkpointer-friendly (JSON-serializable).
- We persist a fixed `deadline_ts` (epoch seconds) in state.metrics to enforce
  a total timeout even across async awaits.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.core.settings import Settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_budget_initialized(state: dict, settings: Settings) -> dict:
    """Initialize budget metadata inside state.metrics if missing."""
    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    budget = metrics.get("budget")
    if not isinstance(budget, dict):
        budget = {}

    if "deadline_ts" not in budget:
        total = float(settings.kb_chat_total_timeout_seconds)
        budget = {
            **budget,
            "total_timeout_seconds": total,
            "started_at": now_iso(),
            "deadline_ts": time.time() + max(total, 0.0),
        }

    metrics = {**metrics, "budget": budget}
    return {"metrics": metrics}


def budget_exceeded(state: dict, settings: Settings) -> tuple[bool, str]:
    """Return (exceeded, reason) for any configured KB chat budgets."""
    metrics = state.get("metrics")
    budget = metrics.get("budget") if isinstance(metrics, dict) else None
    deadline_ts = budget.get("deadline_ts") if isinstance(budget, dict) else None

    if isinstance(deadline_ts, (int, float)) and time.time() > float(deadline_ts):
        return True, "budget_exhausted"

    loop_counts = state.get("loop_counts")
    if isinstance(loop_counts, dict):
        total_rounds = int(loop_counts.get("total_rounds") or 0)
        retrieval_retries = int(loop_counts.get("retrieval_retries") or 0)
        generation_retries = int(loop_counts.get("generation_retries") or 0)
    else:
        total_rounds = retrieval_retries = generation_retries = 0

    if total_rounds >= int(settings.kb_chat_max_total_rounds):
        return True, "max_total_rounds"
    if retrieval_retries >= int(settings.kb_chat_max_retrieval_retries):
        return True, "max_retrieval_retries"
    if generation_retries >= int(settings.kb_chat_max_generation_retries):
        return True, "max_generation_retries"

    return False, ""


def remaining_budget_seconds(
    state: dict, settings: Settings, *, now_ts: float | None = None
) -> float:
    """Return remaining budget seconds based on deadline_ts (>= 0)."""
    metrics = state.get("metrics")
    budget = metrics.get("budget") if isinstance(metrics, dict) else None
    deadline_ts = budget.get("deadline_ts") if isinstance(budget, dict) else None
    if not isinstance(deadline_ts, (int, float)):
        total = float(settings.kb_chat_total_timeout_seconds)
        return max(total, 0.0)
    now_value = time.time() if now_ts is None else float(now_ts)
    return max(0.0, float(deadline_ts) - now_value)


def budget_exhausted(state: dict, settings: Settings) -> bool:
    """Return True if remaining budget is depleted."""
    return remaining_budget_seconds(state, settings) <= 0.0


def effective_timeout_seconds(
    component_timeout_seconds: float | None, remaining_seconds: float
) -> float:
    """Clamp component timeout by remaining budget (>= 0)."""
    remaining = max(float(remaining_seconds), 0.0)
    if component_timeout_seconds is None:
        return remaining
    return max(0.0, min(float(component_timeout_seconds), remaining))
