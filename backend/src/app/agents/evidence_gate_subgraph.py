"""Evidence gate subgraph for KB Chat flowchart Stage 5."""

from __future__ import annotations

from functools import partial
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send

from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.agents.kb_chat_agentic_state import (
    DocGateContextInput,
    DocGateDispatchInput,
    DocGateFuseInput,
    DocGateRouteInput,
    KbChatInternalState,
    merge_routing_decision,
)
from app.core.settings import Settings
from app.utils.token_counter import count_tokens_approximately

_TERM_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}")


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _resolve_query_text(state: dict[str, Any]) -> str:
    for key in ("normalized_query", "coref_query", "rewrite_input_query", "user_input"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_terms(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TERM_RE.finditer(text or "")}


def _emit_gate_result(
    *,
    gate: str,
    round_id: int,
    passed: bool,
    score: float,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "doc_gate_runs": [
            {
                "gate": gate,
                "round": round_id,
                "passed": passed,
                "score": round(max(0.0, min(1.0, score)), 4),
                "reason": reason,
                "extra": extra or {},
            }
        ]
    }


def _gate_stage_summary(run: dict[str, Any]) -> dict[str, Any]:
    score_raw = run.get("score")
    score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
    reason = run.get("reason")
    summary: dict[str, Any] = {
        "passed": bool(run.get("passed")),
        "score": round(max(0.0, min(1.0, score)), 4),
        "reason": str(reason) if isinstance(reason, str) else "unknown",
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
    return 0


def _collect_doc_gate_round_runs(state: dict[str, Any]) -> tuple[int, dict[str, dict[str, Any]]]:
    active_round = _resolve_doc_gate_round(state) or 1
    runs_raw = state.get("doc_gate_runs")
    runs = [item for item in runs_raw if isinstance(item, dict)] if isinstance(runs_raw, list) else []
    round_runs = [
        item
        for item in runs
        if isinstance(item.get("round"), int) and int(item.get("round")) == active_round
    ]
    return active_round, {str(item.get("gate") or ""): item for item in round_runs}


def _build_doc_gate_fuse_summary(state: dict[str, Any]) -> dict[str, Any]:
    active_round, by_gate = _collect_doc_gate_round_runs(state)
    suff = by_gate.get("sufficiency", {"passed": False, "score": 0.0, "reason": "missing"})
    ans = by_gate.get("answerability", {"passed": False, "score": 0.0, "reason": "missing"})
    conflict = by_gate.get("conflict", {"passed": False, "score": 0.0, "reason": "missing"})
    conflict_extra = conflict.get("extra") if isinstance(conflict.get("extra"), dict) else {}
    conflict_level = str(conflict_extra.get("conflict_level") or "none")
    missing_gates = [
        gate for gate in ("sufficiency", "answerability", "conflict") if gate not in by_gate
    ]
    decision = "pass"
    if missing_gates:
        decision = "retry"
    elif not bool(ans.get("passed")):
        decision = "exit_unanswerable"
    elif not bool(suff.get("passed")):
        decision = "retry"
    elif conflict_level == "severe":
        decision = "retry_conflict"
    elif not bool(conflict.get("passed")):
        decision = "retry"
    score = (
        float(suff.get("score") or 0.0)
        + float(ans.get("score") or 0.0)
        + float(conflict.get("score") or 0.0)
    ) / 3.0
    return {
        "round": active_round,
        "decision": decision,
        "score": round(max(0.0, min(1.0, score)), 4),
        "sufficiency": suff,
        "answerability": ans,
        "conflict": conflict,
        "conflict_level": conflict_level,
        "conflict_flag": conflict_level == "severe",
        "missing_gates": missing_gates,
    }


def _doc_gate_dispatch(state: DocGateDispatchInput) -> Command[str]:
    next_round = _resolve_doc_gate_round(state) + 1
    branch_state = {**state, "doc_gate_round": next_round}
    return Command(
        update={"doc_gate_round": next_round},
        goto=[
            Send(
                "doc_gate_sufficiency",
                {
                    **branch_state,
                    "doc_gate_task": {"gate": "sufficiency", "round": next_round},
                },
            ),
            Send(
                "doc_gate_answerability",
                {
                    **branch_state,
                    "doc_gate_task": {"gate": "answerability", "round": next_round},
                },
            ),
            Send(
                "doc_gate_conflict",
                {
                    **branch_state,
                    "doc_gate_task": {"gate": "conflict", "round": next_round},
                },
            ),
        ],
    )


def _doc_gate_sufficiency(state: DocGateContextInput) -> dict[str, Any]:
    round_id = _resolve_doc_gate_round(state) or 1
    context = str(state.get("final_context") or "")
    tokens = count_tokens_approximately(context)
    evidence_count = len(re.findall(r"\[[^\]]+\]", context))
    passed = evidence_count >= 1 and tokens >= 48
    score = min(1.0, (evidence_count * 0.2) + (tokens / 1200.0))
    reason = "passed" if passed else ("too_short" if tokens < 48 else "missing_evidence")
    return _emit_gate_result(
        gate="sufficiency",
        round_id=round_id,
        passed=passed,
        score=score,
        reason=reason,
        extra={"tokens": tokens, "evidence_count": evidence_count},
    )


def _doc_gate_answerability(state: DocGateContextInput) -> dict[str, Any]:
    round_id = _resolve_doc_gate_round(state) or 1
    query = _resolve_query_text(state)
    context = str(state.get("final_context") or "")
    q_terms = _extract_terms(query)
    c_terms = _extract_terms(context)
    overlap = len(q_terms & c_terms)
    denominator = max(len(q_terms), 1)
    ratio = overlap / denominator
    passed = ratio >= 0.2 or len(context.strip()) > 120
    reason = "passed" if passed else "low_overlap"
    return _emit_gate_result(
        gate="answerability",
        round_id=round_id,
        passed=passed,
        score=ratio,
        reason=reason,
        extra={"overlap": overlap, "query_terms": len(q_terms)},
    )


def _doc_gate_conflict(state: DocGateContextInput) -> dict[str, Any]:
    round_id = _resolve_doc_gate_round(state) or 1
    context = str(state.get("final_context") or "")
    conflict_markers = (
        context.count("但是")
        + context.count("然而")
        + context.lower().count("however")
        + context.lower().count("but ")
    )
    labels = re.findall(r"\[([^\[\]\n]{1,128})\]", context)
    conflict_pairs = [
        [labels[idx], labels[idx + 1]]
        for idx in range(0, max(len(labels) - 1, 0))
        if idx < len(labels) - 1
    ][:4]
    if conflict_markers >= 3:
        conflict_level = "severe"
    elif conflict_markers >= 1:
        conflict_level = "light"
    else:
        conflict_level = "none"
    score = min(1.0, conflict_markers / 4.0)
    passed = conflict_level != "severe"
    reason = (
        "passed"
        if conflict_level == "none"
        else "light_conflict"
        if conflict_level == "light"
        else "severe_conflict"
    )
    return _emit_gate_result(
        gate="conflict",
        round_id=round_id,
        passed=passed,
        score=1.0 - score,
        reason=reason,
        extra={
            "conflict_markers": conflict_markers,
            "conflict_level": conflict_level,
            "conflict_pairs": conflict_pairs,
        },
    )


def _doc_gate_fuse(state: DocGateFuseInput) -> dict[str, Any]:
    summary = _build_doc_gate_fuse_summary(state)
    suff = summary["sufficiency"]
    ans = summary["answerability"]
    conflict = summary["conflict"]
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    return {
        "stage_summaries": {
            **stage_summaries,
            "doc_gate_sufficiency": _gate_stage_summary(suff),
            "doc_gate_answerability": _gate_stage_summary(ans),
            "doc_gate_conflict": _gate_stage_summary(conflict),
            "doc_gate_fuse": summary,
        },
    }


def _doc_gate_route(state: DocGateRouteInput, settings: Settings) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    scores = _build_doc_gate_fuse_summary(state)
    decision = str(scores.get("decision") or "retry")
    score = float(scores.get("score") or 0.0)
    loop_counts = state.get("loop_counts")
    retrieval_retries = (
        int(loop_counts.get("retrieval_retries") or 0)
        if isinstance(loop_counts, dict)
        else 0
    )
    if decision == "pass":
        action = "none"
        goto = "answer_subgraph"
        passed = True
        reason = "passed"
    elif decision == "exit_unanswerable":
        action = "force_exit"
        goto = "force_exit"
        passed = False
        reason = "exit_unanswerable"
    elif decision == "retry_conflict":
        max_retries = int(settings.kb_chat_max_retrieval_retries)
        if retrieval_retries >= max_retries:
            action = "force_exit"
            goto = "force_exit"
            passed = False
            reason = "conflict_retry_exhausted"
        else:
            action = "transform_query"
            goto = "transform_query"
            passed = False
            reason = "severe_conflict"
    else:
        action = "transform_query"
        goto = "transform_query"
        passed = False
        reason = "retry"
    reflection = state.get("reflection")
    reflection = reflection if isinstance(reflection, dict) else {}
    retry_advice = (
        "none"
        if decision == "pass"
        else (
            "exit"
            if decision in {"exit_unanswerable", "retry_conflict"}
            and reason == "conflict_retry_exhausted"
            else "retry"
        )
    )
    routing_decision = {
        "phase": "doc_gate",
        "next_node": goto,
        "action": action,
        "reason": reason,
        "reason_code": decision,
        "decision_source": "parallel_gate",
        "retry_advice": retry_advice,
        "score": round(score, 4),
        "retry_budget_snapshot": {
            "retrieval_retries": retrieval_retries,
            "max_retrieval_retries": int(settings.kb_chat_max_retrieval_retries),
        },
        "round_id": _resolve_doc_gate_round(state) or 1,
    }
    return {
        "reflection": {
            **reflection,
            "relevance_passed": passed,
            "action": action,
            "reason": reason,
            "confidence": round(score, 4),
            "decision_source": "parallel_gate",
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
                "decision_source": "parallel_gate",
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
        "doc_gate_dispatch",
        _doc_gate_dispatch,
        side_effect_type="deterministic_rule",
        retry_disabled_reason="parallel_fanout",
        destinations=(
            "doc_gate_sufficiency",
            "doc_gate_answerability",
            "doc_gate_conflict",
        ),
    )
    add_traced_node("doc_gate_sufficiency", _doc_gate_sufficiency, side_effect_type="deterministic_rule")
    add_traced_node(
        "doc_gate_answerability",
        _doc_gate_answerability,
        side_effect_type="deterministic_rule",
    )
    add_traced_node("doc_gate_conflict", _doc_gate_conflict, side_effect_type="deterministic_rule")
    add_traced_node("doc_gate_fuse", _doc_gate_fuse, side_effect_type="deterministic_rule")
    add_traced_node(
        "doc_gate_route",
        partial(_doc_gate_route, settings=settings),
        side_effect_type="deterministic_rule",
    )

    graph.set_entry_point("doc_gate_dispatch")
    graph.add_edge("doc_gate_sufficiency", "doc_gate_fuse")
    graph.add_edge("doc_gate_answerability", "doc_gate_fuse")
    graph.add_edge("doc_gate_conflict", "doc_gate_fuse")
    graph.add_edge("doc_gate_fuse", "doc_gate_route")
    graph.add_edge("doc_gate_route", END)
    return graph.compile(name="kb_chat_evidence_gate_subgraph")
