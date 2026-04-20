"""KB Chat preprocess 上下文阶段节点。"""

from __future__ import annotations

import time
from typing import Any

from langgraph.runtime import Runtime

from app.agents.kb_chat_memory import (
    aget_kb_chat_memory,
    kb_chat_memory_distinct_entries,
    render_kb_chat_memory_snippet,
    resolve_kb_chat_store_user_id,
)
from app.agents.kb_chat_agentic_state import (
    AmbiguityCheckInput,
    CorefRewriteInput,
    MergeContextInput,
    NormalizeRewriteInput,
    merge_routing_decision,
)
from app.core.settings import Settings
from app.services.kb_chat_context_seed import (
    build_context_seed_from_messages,
    context_seed_turns_to_context_frame_turns,
)
from app.services.query_rewrite_service import QueryRewriteService

from .budget import ensure_budget_initialized, now_iso
from .preprocess_context_helpers import (
    _filter_memory_entries_already_covered_by_turns,
    _generate_summary_from_turns,
    _latest_summary_message,
    _needs_conflict_resolution,
    _recent_turns,
    _render_display_context,
    _select_turns_for_merge,
    _strip_summary_prefix,
    trim_kb_preprocess_messages,
)
from .preprocess_query_bundle import _extract_user_input, _merge_stage_summary, _runtime_context


async def merge_context(
    state: MergeContextInput,
    runtime: Runtime[Any],
    settings: Settings,
) -> dict[str, Any]:
    """将 summary / memory / user_input 合并为 `merged_context`（骨架实现）。

    Current implementation uses user_input + optional summary system message.
    """
    start = time.perf_counter()
    updates: dict[str, Any] = {}

    # 预算元数据存放在 metrics 中，便于 checkpointer 处理。
    updates.update(ensure_budget_initialized(state, settings))

    messages = state.get("messages")
    if not isinstance(messages, list):
        messages = []
    trimmed_messages, trim_stats = trim_kb_preprocess_messages(
        messages,
        settings=settings,
    )
    messages = trimmed_messages

    user_input = _extract_user_input(state)
    persisted_summary = _latest_summary_message(messages)
    summary_text = _strip_summary_prefix(persisted_summary)
    summary_source = "persisted" if summary_text else "none"
    turns = _recent_turns(messages, max_turns=6)
    if not summary_text:
        generated = await _generate_summary_from_turns(turns=turns, settings=settings)
        if generated:
            summary_text = generated
            summary_source = "generated"

    question = user_input.strip()
    memory_data: dict[str, Any] | None = None
    memory_snippet = ""
    memory_candidates = 0
    memory_retained = 0
    memory_retained_distinct = 0
    memory_rendered = 0
    memory_recall_precision: float | None = None
    if settings.memory_enabled and runtime.store is not None:
        context = _runtime_context(runtime)
        raw_memory_keys = state.get("memory_keys")
        keys = raw_memory_keys if isinstance(raw_memory_keys, dict) else {}
        thread_id = str(context.get("thread_id") or keys.get("thread_id") or "").strip()
        user_id = resolve_kb_chat_store_user_id(
            user_id=context.get("user_id") or keys.get("user_id"),
            thread_id=thread_id,
        )
        kb_ids_raw = context.get("kb_ids")
        if not isinstance(kb_ids_raw, list):
            keys_kb_ids = keys.get("kb_ids")
            kb_ids_raw = keys_kb_ids if isinstance(keys_kb_ids, list) else []
        kb_ids = [str(k) for k in kb_ids_raw if isinstance(k, str) and k.strip()]
        try:
            mem = await aget_kb_chat_memory(
                store=runtime.store,
                user_id=user_id,
                thread_id=thread_id,
                kb_ids=kb_ids,
                query=question,
                limit=settings.kb_chat_memory_search_limit,
            )
            if isinstance(mem, dict):
                memory_data = mem
                raw_entries = mem.get("entries")
                if isinstance(raw_entries, list):
                    memory_candidates = len([entry for entry in raw_entries if isinstance(entry, dict)])
                memory_snippet = render_kb_chat_memory_snippet(mem)
        except Exception:  # pragma: no cover
            memory_data = None
            memory_snippet = ""

    base_seed = build_context_seed_from_messages(
        summary_text=summary_text,
        messages=messages,
        question=question,
        max_turns=6,
        exclude_question=question,
    )
    summary_text = base_seed["summary_text"]
    turns = context_seed_turns_to_context_frame_turns(base_seed["recent_turns"])
    selected_turns = _select_turns_for_merge(
        turns,
        question=question,
        has_summary=bool(summary_text),
    )
    merge_notes: list[str] = []
    llm_resolve_used = False
    llm_resolve_reason: str | None = None
    fallback_used = False
    keep_memory = True
    if _needs_conflict_resolution(
        summary_text=summary_text, memory_snippet=memory_snippet
    ):
        llm_resolve_used = True
        try:
            svc = QueryRewriteService(settings=settings)
            resolve = await svc.resolve_merge_context_conflict(
                question=question,
                summary_text=summary_text,
                memory_snippet=memory_snippet,
            )
            if resolve.success:
                summary_text = resolve.summary_text or summary_text
                keep_memory = bool(resolve.keep_memory)
                merge_notes = resolve.notes
            else:
                fallback_used = True
            llm_resolve_reason = resolve.reason
        except Exception:  # pragma: no cover
            fallback_used = True
            llm_resolve_reason = "error"

    filtered_memory = (
        _filter_memory_entries_already_covered_by_turns(
            memory_data,
            question=question,
            turns=selected_turns,
        )
        if keep_memory
        else None
    )
    memory_for_render = (
        render_kb_chat_memory_snippet(filtered_memory)
        if filtered_memory is not None
        else (memory_snippet if keep_memory else "")
    )
    if isinstance(filtered_memory, dict):
        filtered_entries = filtered_memory.get("entries")
        if isinstance(filtered_entries, list):
            memory_retained = len(
                [entry for entry in filtered_entries if isinstance(entry, dict)]
            )
        memory_retained_distinct = len(kb_chat_memory_distinct_entries(filtered_memory))
    elif memory_data is not None:
        memory_retained = memory_candidates
        memory_retained_distinct = len(kb_chat_memory_distinct_entries(memory_data))
    memory_rendered = max(
        sum(1 for line in memory_for_render.splitlines() if line.startswith("- ")),
        0,
    )
    if memory_retained_distinct > 0:
        memory_recall_precision = round(
            min(memory_rendered, memory_retained_distinct) / memory_retained_distinct,
            4,
        )
    merged_context = _render_display_context(
        summary=f"对话摘要：\n{summary_text}" if summary_text else "",
        turns=selected_turns,
        memory_snippet=memory_for_render,
        question=question,
    )
    merged = merged_context or question
    rewrite_input_query = question
    context_frame: dict[str, Any] = {
        "summary_text": summary_text,
        "summary_source": summary_source,
        "recent_turns": turns,
        "selected_turns": selected_turns,
        "memory_snippet": memory_for_render,
        "current_question": question,
        "merge_strategy": "builtin_summary_first",
        "merge_fallback_used": fallback_used,
        "merge_notes": merge_notes,
    }
    source_chars = (
        len(summary_text)
        + sum(len((turn.get("text") or "").strip()) for turn in turns)
        + len(memory_for_render)
        + len(question)
    )
    compression_ratio = round(len(merged) / source_chars, 4) if source_chars else 1.0

    stage_summaries = _merge_stage_summary(
        state,
        "merge_context",
        {
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "memory_included": bool(memory_for_render),
            "memory_candidates": memory_candidates,
            "memory_retained": memory_retained,
            "memory_retained_distinct": memory_retained_distinct,
            "memory_rendered": memory_rendered,
            "memory_recall_precision": memory_recall_precision,
            "input_source": "user_input",
            "input_chars": len(question),
            "output_chars": len(merged),
            "summary_source": summary_source,
            "turns_seen": len(turns),
            "turns_selected": len(selected_turns),
            "compression_ratio": compression_ratio,
            **trim_stats,
            "llm_resolve_used": llm_resolve_used,
            "llm_resolve_reason": llm_resolve_reason,
            "fallback_used": fallback_used,
            "completed_at": now_iso(),
        },
        settings=settings,
    )

    return {
        **updates,
        "user_input": user_input,
        "context_frame": context_frame,
        "rewrite_input_query": rewrite_input_query,
        "merged_context": merged,
        "stage_summaries": stage_summaries,
    }


async def coref_rewrite(state: CorefRewriteInput, settings: Settings) -> dict[str, Any]:
    """执行指代消解 / 改写；失败时退回原始问题。"""
    start = time.perf_counter()
    input_source = "rewrite_input_query"
    query = state.get("rewrite_input_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
        input_source = "user_input"

    rewritten = query
    reason: str | None = None
    meta: dict[str, Any] = {}
    context_frame = state.get("context_frame")
    context_data = context_frame if isinstance(context_frame, dict) else {}
    raw_selected_turns = context_data.get("selected_turns")
    selected_turns = raw_selected_turns if isinstance(raw_selected_turns, list) else []
    summary_text = (
        str(context_data.get("summary_text"))
        if isinstance(context_data.get("summary_text"), str)
        else ""
    )
    memory_snippet = (
        str(context_data.get("memory_snippet"))
        if isinstance(context_data.get("memory_snippet"), str)
        else ""
    )
    try:
        svc = QueryRewriteService(settings=settings)
        recent_turns: list[dict[str, str]] = [
            {
                "role": str(item.get("role")).strip(),
                "text": str(item.get("text")).strip(),
            }
            for item in selected_turns
            if isinstance(item, dict)
            and isinstance(item.get("role"), str)
            and isinstance(item.get("text"), str)
        ]
        result = await svc.resolve_reference(
            query,
            enabled=True,
            recent_turns=recent_turns,
            summary_text=summary_text,
            memory_snippet=memory_snippet,
        )
        rewritten = result.query
        reason = result.reason
        if isinstance(result.meta, dict):
            meta = result.meta
    except Exception:  # pragma: no cover
        # 最终兜底：保留原始问题。
        rewritten = query
        reason = "error"
        meta = {
            "triggered": False,
            "confidence": 0.0,
            "selected_mention": "",
            "resolution_source": "fail_open",
            "reasoning": "",
            "needs_clarification": False,
        }

    stage_summaries = _merge_stage_summary(
        state,
        "resolve_reference",
        {
            "rewritten": rewritten != query,
            "reason": reason,
            "input_source": input_source,
            "input_chars": len(query.strip()),
            "output_chars": len(rewritten.strip()),
            "changed_ratio": (
                round(
                    abs(len(rewritten.strip()) - len(query.strip()))
                    / len(query.strip()),
                    4,
                )
                if query.strip()
                else 0.0
            ),
            "triggered": bool(meta.get("triggered")),
            "confidence": float(meta.get("confidence") or 0.0),
            "selected_mention": str(meta.get("selected_mention") or ""),
            "resolution_source": str(meta.get("resolution_source") or "none"),
            "reasoning": str(meta.get("reasoning") or ""),
            "fallback_reason": (
                str(meta.get("fallback_reason") or reason or "")
                if str(meta.get("resolution_source") or "none") == "fail_open"
                else None
            ),
            "needs_clarification_hint": bool(meta.get("needs_clarification")),
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )

    return {
        "resolved_query": rewritten,
        "reference_resolution_meta": meta,
        "coref_query": rewritten,
        "coref_meta": meta,
        "stage_summaries": stage_summaries,
    }


async def ambiguity_check(
    state: AmbiguityCheckInput, settings: Settings
) -> dict[str, Any]:
    """使用模型优先决策执行歧义检查，并生成结构化澄清载荷。"""
    start = time.perf_counter()
    query = state.get("resolved_query")
    if not isinstance(query, str) or not query.strip():
        query = state.get("coref_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    ambiguous = False
    reverse_question = ""
    reason: str | None = None
    failure_reason: str | None = None
    reason_code: str | None = None
    confidence: float | None = None
    model_reason: str | None = None
    fallback_used = False
    clarification_payload: dict[str, Any] | None = None

    coref_meta = state.get("reference_resolution_meta")
    if not isinstance(coref_meta, dict):
        coref_meta = state.get("coref_meta")
    coref_meta_payload = dict(coref_meta) if isinstance(coref_meta, dict) else None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.ambiguity_check(
            query,
            enabled=True,
            coref_meta=coref_meta_payload,
        )
        ambiguous = result.ambiguous
        reverse_question = result.reverse_question or ""
        reason = result.reason
        failure_reason = result.failure_reason
        reason_code = result.reason_code
        confidence = result.confidence
        model_reason = result.model_reason
        fallback_used = bool(result.fallback_used)
        if isinstance(result.clarification_payload, dict):
            clarification_payload = result.clarification_payload
    except Exception:  # pragma: no cover
        ambiguous = False
        reverse_question = ""
        reason = "未命中需澄清信号，可直接继续检索。"
        failure_reason = "error"
        model_reason = reason
        fallback_used = True

    slot_count = 0
    if isinstance(clarification_payload, dict):
        slots = clarification_payload.get("slots")
        if isinstance(slots, list):
            slot_count = len(slots)

    stage_summaries = _merge_stage_summary(
        state,
        "ambiguity_check",
        {
            "ambiguous": ambiguous,
            "reason": reason,
            "failure_reason": failure_reason,
            "reason_code": reason_code,
            "confidence": confidence,
            "model_reason": model_reason,
            "fallback_used": fallback_used,
            "slot_count": slot_count,
            "clarification_payload": clarification_payload,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )

    if not ambiguous:
        return {
            "reflection": {"action": "none"},
            "stage_summaries": stage_summaries,
        }

    return {
        "reflection": {
            "action": "clarify",
            "reason": "ambiguous_query",
            "reason_code": reason_code or "mixed",
            "confidence": confidence,
        },
        "final_answer": reverse_question,
        "clarification_payload": clarification_payload,
        "stage_summaries": stage_summaries,
        **merge_routing_decision(
            state,
            "preprocess",
            {
                "phase": "preprocess",
                "next_node": "force_exit",
                "action": "clarify",
                "reason": "ambiguous_query",
                "reason_code": reason_code or "mixed",
                "decision_source": "ambiguity_check",
                "completed_at": now_iso(),
            },
        ),
    }


async def normalize_rewrite(
    state: NormalizeRewriteInput,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """用仅依赖 LLM 的结构化输出规范问题，并在失败时开放降级。"""
    start = time.perf_counter()
    _ = runtime
    input_source = "resolved_query"
    query = state.get("resolved_query")
    if not isinstance(query, str) or not query.strip():
        query = state.get("coref_query")
        input_source = "coref_query"
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
        input_source = "user_input"

    rewritten = query
    rewritten_flag = False
    normalization_source = "fail_open"
    fallback_reason = "error"
    normalized_meta: dict[str, Any] = {
        "source": "fail_open",
        "fallback_reason": "error",
        "aliases": [],
        "entities": [],
        "time_constraints": [],
        "metric_constraints": [],
        "scope_constraints": [],
        "recall_risk": "medium",
        "drift_risk": False,
        "constraint_preserved": True,
        "reasoning": "",
    }
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.normalize_rewrite(query)
        rewritten = result.query
        rewritten_flag = result.rewritten
        if isinstance(result.meta, dict):
            normalized_meta = {**normalized_meta, **result.meta}
        normalization_source = str(normalized_meta.get("source") or "fail_open")
        if normalization_source == "fail_open":
            fallback_reason = str(
                normalized_meta.get("fallback_reason") or result.reason or ""
            )
        else:
            fallback_reason = ""
    except Exception:  # pragma: no cover
        rewritten = query
        rewritten_flag = False

    raw_normalized_aliases = normalized_meta.get("aliases")
    normalized_aliases = (
        raw_normalized_aliases if isinstance(raw_normalized_aliases, list) else []
    )

    stage_summaries = _merge_stage_summary(
        state,
        "query_normalize",
        {
            "rewritten": rewritten_flag,
            "normalization_source": normalization_source,
            "fallback_reason": fallback_reason or None,
            "guardrail_reason": str(normalized_meta.get("guardrail_reason") or "")
            or None,
            "alias_count": len(
                [a for a in normalized_aliases if isinstance(a, str) and a.strip()]
            ),
            "constraint_preserved": bool(
                normalized_meta.get("constraint_preserved", True)
            ),
            "drift_risk": bool(normalized_meta.get("drift_risk", False)),
            "recall_risk": str(normalized_meta.get("recall_risk") or "medium"),
            "input_source": input_source,
            "input_chars": len(query.strip()),
            "output_chars": len(rewritten.strip()),
            "changed_ratio": (
                round(
                    abs(len(rewritten.strip()) - len(query.strip()))
                    / len(query.strip()),
                    4,
                )
                if query.strip()
                else 0.0
            ),
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )
    return {
        "normalized_query": rewritten,
        "normalized_meta": normalized_meta,
        "stage_summaries": stage_summaries,
    }


