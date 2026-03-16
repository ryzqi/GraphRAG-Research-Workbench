"""Shared dispatch/fuse helpers for rewrite and subquery fan-out."""

from __future__ import annotations

from typing import Any

from langgraph.types import Send


def make_send_task(node: str, payload: dict[str, Any], state: dict[str, Any]) -> Send:
    """Attach only branch-local state required for fan-out execution."""

    branch_state = {**payload}
    loop_counts = state.get("loop_counts")
    if isinstance(loop_counts, dict):
        branch_state["loop_counts"] = loop_counts
    retrieval_budget = state.get("retrieval_budget")
    if isinstance(retrieval_budget, dict) and retrieval_budget:
        branch_state["retrieval_budget"] = retrieval_budget
    return Send(node, branch_state)

def sort_by_priority_then_index(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order fan-out runs deterministically for stable merge output."""

    return sorted(
        runs,
        key=lambda item: (
            int(item.get("priority") or 99),
            int(item.get("index") or 0),
        ),
    )


def build_retrieval_payload(
    *,
    query: str,
    kb_ids: list[str],
    top_k: int,
    retrieval_round: int,
    query_items: list[dict[str, Any]] | None = None,
    per_query_top_k: int | None = None,
    global_candidates_limit: int | None = None,
    rerank_input_limit: int | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Build normalized payload for kb_retrieve fan-out invocations."""

    payload: dict[str, Any] = {
        "query": query,
        "kb_ids": kb_ids,
        "top_k": top_k,
        "retrieval_round": retrieval_round,
    }
    if isinstance(query_items, list) and query_items:
        payload["query_items"] = query_items
    if isinstance(per_query_top_k, int) and per_query_top_k > 0:
        payload["per_query_top_k"] = per_query_top_k
    if isinstance(global_candidates_limit, int) and global_candidates_limit > 0:
        payload["global_candidates_limit"] = global_candidates_limit
    if isinstance(rerank_input_limit, int) and rerank_input_limit > 0:
        payload["rerank_input_limit"] = rerank_input_limit
    if isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0:
        payload["timeout_seconds"] = float(timeout_seconds)
    return payload
