"""改写与子查询扇出共用的派发 / 融合辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.types import Send


def make_send_task(
    node: str, payload: dict[str, Any], state: Mapping[str, object]
) -> Send:
    """仅附加扇出分支执行所需的局部状态。"""

    branch_state = {**payload}
    loop_counts = state.get("loop_counts")
    if isinstance(loop_counts, dict):
        branch_state["loop_counts"] = loop_counts
    retrieval_budget = state.get("retrieval_budget")
    if isinstance(retrieval_budget, dict) and retrieval_budget:
        branch_state["retrieval_budget"] = retrieval_budget
    return Send(node, branch_state)


def sort_by_priority_then_index(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按稳定顺序排列扇出结果，保证合并输出可复现。"""

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
    query_items: Sequence[Mapping[str, object]] | None = None,
    per_query_top_k: int | None = None,
    global_candidates_limit: int | None = None,
    rerank_input_limit: int | None = None,
) -> dict[str, Any]:
    """为 kb_retrieve 扇出调用构造规范化载荷。"""

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
    return payload
