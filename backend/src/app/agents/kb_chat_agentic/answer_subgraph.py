"""KB Chat answer generation subgraph.

This subgraph encapsulates draft generation -> review -> optional repair ->
commit. It keeps the parent graph routing contract intact by writing
`reflection.action/reason` and `stage_summaries.answer_subgraph`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, TypedDict

from langchain.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime

from app.agents.kb_chat_agentic.reflection import (
    answer_review,
    generate_draft,
    route_after_answer_review,
)
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings
from app.prompts import get_prompt_loader

from .budget import now_iso

_REPAIRABLE_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
}


class KbChatAnswerSubgraphContext(TypedDict, total=False):
    """Typed runtime context propagated from parent graph."""

    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _get_loop_counts(state: dict[str, Any]) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _merge_stage_summary(
    state: dict[str, Any],
    key: str,
    summary: dict[str, Any],
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {}
    state_stage = state.get("stage_summaries")
    if isinstance(state_stage, dict):
        base = {**state_stage}
    if isinstance(updates, dict):
        updates_stage = updates.get("stage_summaries")
        if isinstance(updates_stage, dict):
            base = {**base, **updates_stage}
    return {"stage_summaries": {**base, key: summary}}


def _merge_subgraph_state(
    state: dict[str, Any],
    patch: dict[str, Any],
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    current = state.get("answer_subgraph_state")
    if isinstance(current, dict):
        merged = {**current}
    if isinstance(updates, dict):
        in_updates = updates.get("answer_subgraph_state")
        if isinstance(in_updates, dict):
            merged = {**merged, **in_updates}
    return {"answer_subgraph_state": {**merged, **patch}}


def _resolve_query_text(state: dict[str, Any]) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


def _route_after_self_check(state: dict[str, Any], settings: Settings) -> str:
    reflection = state.get("reflection")
    passed = reflection.get("review_passed") if isinstance(reflection, dict) else None
    if passed is True:
        return "answer_commit"

    reason = _as_str(reflection.get("reason")) if isinstance(reflection, dict) else ""
    if reason not in _REPAIRABLE_FAILURE_REASONS:
        return "answer_commit"

    loop_counts = _get_loop_counts(state)
    max_generation_retries = int(settings.kb_chat_max_generation_retries)
    if loop_counts["generation_retries"] >= max_generation_retries:
        return "answer_commit"

    subgraph_state = state.get("answer_subgraph_state")
    repair_attempts = (
        int(subgraph_state.get("repair_attempts") or 0)
        if isinstance(subgraph_state, dict)
        else 0
    )
    if repair_attempts >= max_generation_retries:
        return "answer_commit"
    return "answer_repair"


async def _draft_generate(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    _ = runtime
    updates = await generate_draft(state, settings=settings, chat_model=chat_model)
    return {
        **updates,
        **_merge_subgraph_state(
            state,
            {
                "phase": "draft_generate",
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


async def _answer_self_check(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    _ = runtime
    updates = await answer_review(state, settings=settings, chat_model=chat_model)
    return {
        **updates,
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_self_check",
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


async def _answer_repair(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    _ = runtime
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    loop_counts = {
        **loop_counts,
        "total_rounds": loop_counts["total_rounds"] + 1,
        "generation_retries": loop_counts["generation_retries"] + 1,
    }

    draft_answer = _as_str(state.get("draft_answer")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    question = _resolve_query_text(state)

    repaired_answer = draft_answer
    fallback_reason: str | None = None
    if draft_answer and final_context and question:
        prompts = get_prompt_loader()
        try:
            repair_system = prompts.render_with_few_shot("kb_chat/system")
        except KeyError:
            repair_system = (
                "你是知识库回答修复器。"
                "仅基于参考内容修复回答并补齐有效引用，禁止新增无依据事实。"
            )
        repair_user = (
            "请修复回答，仅输出最终答案正文。\n"
            "要求：\n"
            "1) 仅使用参考内容中的事实；\n"
            "2) 关键事实必须附带有效 [Sx] 引用；\n"
            "3) 不能引入参考内容外信息。\n\n"
            f"问题：{question}\n\n"
            f"参考内容：\n{final_context}\n\n"
            f"原回答：\n{draft_answer}"
        )
        model = chat_model.bind(max_tokens=1024)
        try:
            msg = await model.ainvoke(
                [
                    SystemMessage(content=repair_system),
                    HumanMessage(content=repair_user),
                ]
            )
            candidate = _as_str(getattr(msg, "content", "")).strip()
            if candidate:
                repaired_answer = candidate
            else:
                fallback_reason = "empty_repair_output"
        except asyncio.CancelledError:
            raise
        except Exception:
            fallback_reason = "repair_invoke_failed"
    else:
        fallback_reason = "repair_input_missing"

    subgraph_state = state.get("answer_subgraph_state")
    repair_attempts = (
        int(subgraph_state.get("repair_attempts") or 0)
        if isinstance(subgraph_state, dict)
        else 0
    ) + 1
    updates: dict[str, Any] = {
        "loop_counts": loop_counts,
        "draft_answer": repaired_answer,
        "final_answer": repaired_answer,
    }
    updates = {
        **updates,
        **_merge_stage_summary(
            state,
            "answer_repair",
            {
                "repair_attempt": repair_attempts,
                "fallback_reason": fallback_reason,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
            updates=updates,
        ),
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_repair",
                "repair_attempts": repair_attempts,
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }
    return updates


async def _answer_commit(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> dict[str, Any]:
    _ = runtime
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    loop_counts = _get_loop_counts(state)
    repair_attempts = 0
    subgraph_state = state.get("answer_subgraph_state")
    if isinstance(subgraph_state, dict):
        repair_attempts = int(subgraph_state.get("repair_attempts") or 0)

    next_step = route_after_answer_review(state, settings)
    reason = _as_str(reflection_obj.get("reason")).strip()
    degrade_reason: str | None = None
    reflection_patch: dict[str, Any] = {}

    if loop_counts["generation_retries"] >= int(settings.kb_chat_max_generation_retries):
        next_step = "force_exit"
        degrade_reason = "max_generation_retries"
        reflection_patch = {
            "action": "force_exit",
            "reason": "max_generation_retries",
            "review_passed": False,
        }
    elif next_step == "force_exit":
        degrade_reason = reason or "force_exit"
        reflection_patch = {"action": "force_exit"}
    elif next_step == "transform_query":
        degrade_reason = reason or "review_failed"
        reflection_patch = {"action": "transform_query"}
    else:
        reflection_patch = {"action": "none"}

    merged_reflection = {**reflection_obj, **reflection_patch}
    final_answer = _as_str(state.get("final_answer") or state.get("draft_answer")).strip()
    if not final_answer and next_step == "force_exit":
        final_answer = "基于当前信息仍无法稳定回答该问题（已停止重试）。"

    answer_quality = {
        "passed": merged_reflection.get("review_passed") is True,
        "reason": _as_str(merged_reflection.get("reason")).strip(),
        "next_step": next_step,
        "repair_attempts": repair_attempts,
        "generation_retries": loop_counts.get("generation_retries", 0),
        "retrieval_retries": loop_counts.get("retrieval_retries", 0),
    }
    best_answer = _as_str(state.get("best_answer") or state.get("draft_answer")).strip()
    summary = {
        **answer_quality,
        "best_answer": best_answer or None,
        "degrade_reason": degrade_reason,
        "completed_at": now_iso(),
    }

    updates: dict[str, Any] = {
        "reflection": merged_reflection,
        "answer_quality": answer_quality,
        "degrade_reason": degrade_reason,
    }
    if final_answer:
        updates["final_answer"] = final_answer
    return {
        **updates,
        **_merge_stage_summary(state, "answer_subgraph", summary, updates=updates),
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_commit",
                "next_step": next_step,
                "repair_attempts": repair_attempts,
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


def build_answer_subgraph(
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
):
    """Build compiled answer subgraph for parent KB chat graph."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatAnswerSubgraphContext,
    )
    graph.add_node(
        "draft_generate",
        lambda s, runtime: _draft_generate(
            s, runtime, settings=settings, chat_model=chat_model
        ),
    )
    graph.add_node(
        "answer_self_check",
        lambda s, runtime: _answer_self_check(
            s, runtime, settings=settings, chat_model=chat_model
        ),
    )
    graph.add_node(
        "answer_repair",
        lambda s, runtime: _answer_repair(
            s, runtime, settings=settings, chat_model=chat_model
        ),
    )
    graph.add_node(
        "answer_commit",
        lambda s, runtime: _answer_commit(s, runtime, settings=settings),
        defer=True,
    )

    graph.set_entry_point("draft_generate")
    graph.add_edge("draft_generate", "answer_self_check")
    graph.add_conditional_edges(
        "answer_self_check",
        lambda s: _route_after_self_check(s, settings),
        {
            "answer_commit": "answer_commit",
            "answer_repair": "answer_repair",
        },
    )
    graph.add_edge("answer_repair", "answer_self_check")
    graph.add_edge("answer_commit", END)
    return graph.compile(name="kb_chat_answer_subgraph")
