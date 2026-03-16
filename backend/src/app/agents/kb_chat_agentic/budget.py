"""KB Chat budgets (rounds/retries) for agentic graph.

Design notes:
- Budgets must be checkpointer-friendly (JSON-serializable).
- KB chat termination relies only on rounds/retries budgets.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.settings import Settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_budget_initialized(state: dict, settings: Settings) -> dict:
    """Initialize budget metadata inside state.metrics if missing."""
    _ = settings
    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    budget = metrics.get("budget")
    if not isinstance(budget, dict):
        budget = {}

    if "started_at" not in budget:
        budget = {**budget, "started_at": now_iso()}

    metrics = {**metrics, "budget": budget}
    return {"metrics": metrics}


def budget_exceeded(state: dict, settings: Settings) -> tuple[bool, str]:
    """Return (exceeded, reason) for KB chat round/retry budgets."""

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
