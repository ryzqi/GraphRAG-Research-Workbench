"""KB Chat agentic graph helper nodes.

KB Chat runs `kb_retrieve` explicitly in the agentic RAG flow, so it does not need a
generic tool-calling loop here. We keep a small ForceExit helper to produce a safe
final AIMessage when we must stop early (clarify/round-retry budget).
"""

from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage

from app.core.settings import Settings

from .budget import budget_exceeded, now_iso


def force_exit_node(state: dict, settings: Settings) -> dict[str, Any]:
    """Produce a final assistant message when exiting due to clarify/budget."""
    reflection = state.get("reflection")
    action = reflection.get("action") if isinstance(reflection, dict) else None
    review_passed = (
        reflection.get("review_passed") if isinstance(reflection, dict) else None
    )

    reason = ""
    if action == "clarify":
        reason = "clarify"
    else:
        exceeded, why = budget_exceeded(state, settings)
        reason = why if exceeded else "force_exit"

    final_answer = state.get("final_answer")
    draft_answer = state.get("draft_answer")
    best_answer = state.get("best_answer")
    best_answer_meta = state.get("best_answer_meta")
    used_best_answer = False
    if action == "clarify":
        if not isinstance(final_answer, str) or not final_answer.strip():
            final_answer = "为了更准确地回答，请补充必要信息后再提问。"
    else:
        if review_passed is True:
            if not isinstance(final_answer, str) or not final_answer.strip():
                if isinstance(draft_answer, str) and draft_answer.strip():
                    final_answer = draft_answer
        else:
            # Answer didn't pass guardrails; discard any prefilled final answer.
            final_answer = None
        if (
            (not isinstance(final_answer, str) or not final_answer.strip())
            and isinstance(best_answer, str)
            and best_answer.strip()
        ):
            final_answer = best_answer
            used_best_answer = True
        if not isinstance(final_answer, str) or not final_answer.strip():
            final_answer = "根据现有资料无法回答该问题（已停止重试）。"

    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    force_exit_summary: dict[str, Any] = {
        "reason": reason,
        "review_passed": review_passed,
        "used_best_answer": used_best_answer,
        "completed_at": now_iso(),
    }
    if used_best_answer and isinstance(best_answer, str) and best_answer.strip():
        force_exit_summary["best_answer"] = best_answer
    if used_best_answer and isinstance(best_answer_meta, dict):
        force_exit_summary["best_answer_meta"] = best_answer_meta
    stage_summaries = {
        **stage_summaries,
        "force_exit": force_exit_summary,
    }

    return {
        "messages": [AIMessage(content=final_answer)],
        "final_answer": final_answer,
        "stage_summaries": stage_summaries,
    }
