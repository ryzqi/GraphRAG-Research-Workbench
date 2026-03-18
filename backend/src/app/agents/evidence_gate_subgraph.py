"""Evidence gate subgraph for KB Chat flowchart Stage 5."""

from __future__ import annotations

import re
from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.kb_chat_agentic_state import (
    DocGateContextInput,
    DocGateRouteInput,
    KbChatInternalState,
    merge_routing_decision,
)
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.core.settings import Settings
from app.utils.token_counter import count_tokens_approximately


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _gate_stage_summary(run: dict[str, Any]) -> dict[str, Any]:
    score_raw = run.get("score")
    score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
    summary: dict[str, Any] = {
        "passed": bool(run.get("passed")),
        "score": round(max(0.0, min(1.0, score)), 4),
        "reason": str(run.get("reason") or "unknown"),
    }
    extra = run.get("extra")
    if isinstance(extra, dict):
        summary.update(extra)
    return summary


def _resolve_doc_gate_round(state: dict[str, Any]) -> int:
    task = state.get("doc_gate_task")
    if isinstance(task, dict):
        raw = task.get("round")
        if isinstance(raw, int) and raw > 0:
            return raw
    raw_round = state.get("doc_gate_round")
    if isinstance(raw_round, int) and raw_round > 0:
        return raw_round
    runs = state.get("doc_gate_runs")
    if isinstance(runs, list):
        for item in reversed(runs):
            if isinstance(item, dict):
                raw = item.get("round")
                if isinstance(raw, int) and raw > 0:
                    return raw
    return 1


def _resolve_sufficiency_run(state: dict[str, Any]) -> dict[str, Any]:
    active_round = _resolve_doc_gate_round(state)
    runs_raw = state.get("doc_gate_runs")
    runs = [item for item in runs_raw if isinstance(item, dict)] if isinstance(runs_raw, list) else []
    for item in reversed(runs):
        if str(item.get("gate") or "") != "sufficiency":
            continue
        round_value = item.get("round")
        if active_round and isinstance(round_value, int) and round_value != active_round:
            continue
        return item
    return {}


def _doc_gate_sufficiency(state: DocGateContextInput) -> dict[str, Any]:
    round_id = _resolve_doc_gate_round(state)
    context = str(state.get("final_context") or "")
    tokens = count_tokens_approximately(context)
    evidence_count = len(re.findall(r"\[[^\]]+\]", context))
    passed = evidence_count >= 1 and tokens >= 48
    score = min(1.0, (evidence_count * 0.2) + (tokens / 1200.0))
    reason = "passed" if passed else ("too_short" if tokens < 48 else "missing_evidence")
    run = {
        "gate": "sufficiency",
        "round": round_id,
        "passed": passed,
        "score": round(max(0.0, min(1.0, score)), 4),
        "reason": reason,
        "extra": {"tokens": tokens, "evidence_count": evidence_count},
    }
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    return {
        "doc_gate_round": round_id,
        "doc_gate_runs": [run],
        "stage_summaries": {
            **stage_summaries,
            "doc_gate_sufficiency": _gate_stage_summary(run),
        },
    }


def _doc_gate_route(state: DocGateRouteInput, settings: Settings) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    sufficiency = _resolve_sufficiency_run(state)
    passed = sufficiency.get("passed") is True
    score = float(sufficiency.get("score") or 0.0)
    reason = str(sufficiency.get("reason") or ("passed" if passed else "retry"))
    loop_counts = state.get("loop_counts")
    retrieval_retries = (
        int(loop_counts.get("retrieval_retries") or 0)
        if isinstance(loop_counts, dict)
        else 0
    )
    max_retries = int(settings.kb_chat_max_retrieval_retries)
    if passed:
        decision = "pass"
        action = "none"
        goto = "answer_subgraph"
        retry_advice = "none"
    elif retrieval_retries >= max_retries:
        decision = "retry"
        action = "force_exit"
        goto = "force_exit"
        retry_advice = "exit"
        reason = "retry_exhausted"
    else:
        decision = "retry"
        action = "transform_query"
        goto = "transform_query"
        retry_advice = "retry"

    reflection = state.get("reflection")
    reflection = reflection if isinstance(reflection, dict) else {}
    routing_decision = {
        "phase": "doc_gate",
        "next_node": goto,
        "action": action,
        "reason": reason,
        "reason_code": decision,
        "decision_source": "sufficiency_gate",
        "retry_advice": retry_advice,
        "score": round(score, 4),
        "retry_budget_snapshot": {
            "retrieval_retries": retrieval_retries,
            "max_retrieval_retries": max_retries,
        },
        "round_id": _resolve_doc_gate_round(state),
    }
    return {
        "reflection": {
            **reflection,
            "relevance_passed": passed,
            "action": action,
            "reason": reason,
            "confidence": round(score, 4),
            "decision_source": "sufficiency_gate",
            "retry_advice": retry_advice,
        },
        **merge_routing_decision(state, "doc_gate", routing_decision),
        "stage_summaries": {
            **stage_summaries,
            "doc_gate_route": {
                "decision": decision,
                "action": action,
                "goto": goto,
                "passed": passed,
                "reason": reason,
                "score": round(score, 4),
                "retry_advice": retry_advice,
                "decision_source": "sufficiency_gate",
            },
        },
    }


def build_evidence_gate_subgraph(*, settings: Settings):
    """Compile evidence-gate subgraph aligned to flowchart Stage 5."""

    graph = StateGraph(
        state_schema=KbChatInternalState,
        context_schema=KbChatGraphContext,
    )

    def add_traced_node(
        node_id: str,
        node_callable: Any,
        *,
        side_effect_type: str,
        retry_disabled_reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        graph.add_node(
            node_id,
            wrap_kb_chat_node_with_io(node_id, node_callable),
            metadata=extend_kb_chat_node_metadata(
                node_id,
                side_effect_type=side_effect_type,
                retry_enabled=False,
                retry_disabled_reason=retry_disabled_reason or side_effect_type,
            ),
            **kwargs,
        )

    add_traced_node(
        "doc_gate_sufficiency",
        _doc_gate_sufficiency,
        side_effect_type="deterministic_rule",
    )
    add_traced_node(
        "doc_gate_route",
        partial(_doc_gate_route, settings=settings),
        side_effect_type="deterministic_rule",
    )

    graph.set_entry_point("doc_gate_sufficiency")
    graph.add_edge("doc_gate_sufficiency", "doc_gate_route")
    graph.add_edge("doc_gate_route", END)
    return graph.compile(name="kb_chat_evidence_gate_subgraph")
