"""Shared dispatch/fuse helpers for rewrite and subquery fan-out."""

from __future__ import annotations

from typing import Any

from langgraph.types import Send


def make_send_task(node: str, payload: dict[str, Any], state: dict[str, Any]) -> Send:
    """Attach shared runtime keys for fan-out branch execution."""

    return Send(
        node,
        {
            **payload,
            "memory_keys": state.get("memory_keys"),
            "loop_counts": state.get("loop_counts"),
            "runtime_config": state.get("runtime_config"),
        },
    )


def sort_by_retrieval_then_priority(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order branch runs by evidence quality then configured priority."""

    return sorted(
        runs,
        key=lambda item: (
            -int(item.get("retrieval_count") or 0),
            int(item.get("priority") or 99),
        ),
    )


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
    return payload

