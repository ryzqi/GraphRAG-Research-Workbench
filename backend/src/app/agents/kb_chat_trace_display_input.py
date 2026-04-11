"""KB Chat trace 节点输入展示契约。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agents.kb_chat_trace_display_output import (
    _format_evidence_for_node,
    _format_evidence_from_snapshot,
    _format_gate_results,
    _format_review_results,
    _resolve_exit_action,
)
from app.agents.kb_chat_trace_display_shared import (
    DisplayItem,
    NodeLabelResolver,
    _INPUT_CONTRACTS,
    _as_dict,
    _format_query_items,
    _items_from_contract,
    _pick_context_frame_turns,
    _pick_text,
    _resolve_current_subquery_run,
    _resolve_multi_queries_display,
    _resolve_sub_queries_display,
)


def build_node_input_display_items(
    *,
    node_name: str,
    snapshot: Any,
    node_label_resolver: NodeLabelResolver | None = None,
) -> list[DisplayItem]:
    state = _as_dict(snapshot) or {}
    values = _build_input_value_map(
        node_name=node_name,
        snapshot=state,
        node_label_resolver=node_label_resolver,
    )
    return _items_from_contract(_INPUT_CONTRACTS.get(node_name, []), values)

def _build_input_value_map(
    *,
    node_name: str,
    snapshot: Mapping[str, Any],
    node_label_resolver: NodeLabelResolver | None,
) -> dict[str, Any]:
    _ = node_label_resolver
    current_subquery_run = _resolve_current_subquery_run(snapshot)
    values: dict[str, Any] = {
        "user_input": _pick_text(snapshot, "user_input"),
        "recent_turns": _pick_context_frame_turns(snapshot, "recent_turns"),
        "resolved_query": _pick_text(
            snapshot,
            "resolved_query",
            "coref_query",
            "rewrite_input_query",
            "user_input",
        ),
        "normalized_query": _pick_text(
            snapshot,
            "normalized_query",
            "resolved_query",
            "coref_query",
            "rewrite_input_query",
            "user_input",
        ),
        "query_items": _format_query_items(snapshot.get("query_items")),
        "draft_answer": _pick_text(snapshot, "draft_answer", "final_answer"),
        "current_evidence": _format_evidence_from_snapshot(snapshot),
        "subquery": _pick_text(
            _as_dict(snapshot.get("subquery_task")) or current_subquery_run,
            "query",
        ),
        "exit_action": _resolve_exit_action(snapshot),
        "candidate_answer": _pick_text(
            snapshot,
            "candidate_answer",
            "best_answer",
            "draft_answer",
            "final_answer",
        ),
        "gate_results": _format_gate_results(snapshot),
        "review_results": _format_review_results(snapshot),
        "sub_queries": _resolve_sub_queries_display(snapshot),
        "multi_queries": _resolve_multi_queries_display(snapshot),
        "final_answer": _pick_text(snapshot, "final_answer"),
        "retrieved_evidence": _format_evidence_for_node(
            node_name=node_name, snapshot=snapshot
        ),
    }
    if node_name in {"merge_subquery_context", "context_compress"}:
        values["retrieved_evidence"] = _format_evidence_from_snapshot(snapshot)
    if node_name == "retrieve_subquery":
        values["subquery"] = (
            _pick_text(current_subquery_run, "query") or values["subquery"]
        )
    if node_name == "answer_review_fuse":
        values["review_results"] = _format_review_results(snapshot)
    return values


