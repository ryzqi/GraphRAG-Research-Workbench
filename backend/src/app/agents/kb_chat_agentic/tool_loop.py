"""KB Chat agentic graph helper nodes.

KB Chat runs `kb_retrieve` explicitly in the agentic RAG flow, so it does not need a
generic tool-calling loop here. We keep a small ForceExit helper to produce a safe
final AIMessage when we must stop early (clarify/round-retry budget).
"""

from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage

from app.core.settings import Settings
from app.services.evidence_guardrails import resolve_kb_refusal_answer
from app.agents.kb_chat_agentic_state import (
    ForceExitInput,
    resolve_terminal_routing_decision,
)

from .budget import budget_exceeded, now_iso


def force_exit_node(state: ForceExitInput, settings: Settings) -> dict[str, Any]:
    """Produce a final assistant message when exiting due to clarify/budget."""
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    _, terminal_route = resolve_terminal_routing_decision(
        state,
        next_nodes={"force_exit"},
    )
    route_action = str(terminal_route.get("action") or "").strip().lower()
    route_reason = str(terminal_route.get("reason") or "").strip().lower()
    action = route_action or str(reflection_obj.get("action") or "").strip().lower()
    review_passed = (
        reflection_obj.get("review_passed")
        if terminal_route.get("next_node") != "force_exit"
        else False
    )

    reason = ""
    clarification_payload = (
        state.get("clarification_payload")
        if isinstance(state.get("clarification_payload"), dict)
        else None
    )
    if clarification_payload is not None and action != "force_exit":
        action = "clarify"
    if action == "clarify":
        reason = "clarify"
    else:
        exceeded, why = budget_exceeded(state, settings)
        reflection_reason = str(reflection_obj.get("reason") or "").strip().lower()
        reason = route_reason or (why if exceeded else (reflection_reason or "force_exit"))

    final_answer = state.get("final_answer")
    draft_answer = state.get("draft_answer")
    best_answer = state.get("best_answer")
    best_answer_meta = state.get("best_answer_meta")
    used_best_answer = False
    if action == "clarify":
        if clarification_payload and not isinstance(final_answer, str):
            candidate_question = clarification_payload.get("question")
            if isinstance(candidate_question, str) and candidate_question.strip():
                final_answer = candidate_question
        if not isinstance(final_answer, str) or not final_answer.strip():
            final_answer = "为了更准确地回答，请补充关键约束信息后再继续。"
    else:
        if review_passed is True:
            if not isinstance(final_answer, str) or not final_answer.strip():
                if isinstance(draft_answer, str) and draft_answer.strip():
                    final_answer = draft_answer
        else:
            # Answer did not pass guardrails; discard any prefilled final answer.
            final_answer = None
        if (
            (not isinstance(final_answer, str) or not final_answer.strip())
            and isinstance(best_answer, str)
            and best_answer.strip()
        ):
            final_answer = best_answer
            used_best_answer = True
        if not isinstance(final_answer, str) or not final_answer.strip():
            final_answer = resolve_kb_refusal_answer(reason=reason)

    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    force_exit_summary: dict[str, Any] = {
        "reason": reason,
        "action": action,
        "review_passed": review_passed,
        "used_best_answer": used_best_answer,
        "decision_source": terminal_route.get("decision_source"),
        "completed_at": now_iso(),
    }
    if used_best_answer and isinstance(best_answer, str) and best_answer.strip():
        force_exit_summary["best_answer"] = best_answer
    if used_best_answer and isinstance(best_answer_meta, dict):
        force_exit_summary["best_answer_meta"] = best_answer_meta
    if action == "clarify" and isinstance(clarification_payload, dict):
        force_exit_summary["clarification_payload"] = clarification_payload
    stage_summaries = {
        **stage_summaries,
        "force_exit": force_exit_summary,
    }
    reflection_update = {
        **reflection_obj,
        "action": action,
        "reason": reason,
    }
    if review_passed is not None:
        reflection_update["review_passed"] = review_passed

    return {
        "messages": [AIMessage(content=final_answer)],
        "final_answer": final_answer,
        "clarification_payload": clarification_payload,
        "reflection": reflection_update,
        "stage_summaries": stage_summaries,
    }
