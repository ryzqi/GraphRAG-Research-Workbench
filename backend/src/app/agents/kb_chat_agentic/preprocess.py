"""KB Chat agentic preprocess nodes (MergeContext → HyDE).

These nodes are intentionally minimal first:
- Prefer safe no-op / heuristic behaviors
- Defer prompt-heavy LLM behaviors to later tasks (see OpenSpec tasks 1.4/1.11)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.kb_chat_memory import (
    aget_kb_chat_memory,
    render_kb_chat_memory_snippet,
    resolve_kb_chat_store_user_id,
)
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.services.query_rewrite_service import (
    HYDE_NUM_HYPOTHESES,
    QueryRewriteService,
    build_query_items,
)
from app.utils.token_counter import count_tokens_approximately
from app.agents.kb_chat_agentic_state import merge_routing_decision

from .budget import (
    ensure_budget_initialized,
    now_iso,
)
from .json_safety import ensure_json_safe
from .runtime_config import (
    entity_expand_max_candidates,
    entity_expand_max_variants,
    entity_expand_min_confidence,
    entity_expand_timeout_seconds,
    normalize_alias_max,
    normalize_timeout_seconds,
    parallel_retrieval_include_main,
    parallel_retrieval_max_branches,
    parallel_retrieval_min_queries,
)

_COMPLEXITY_CACHE_SCHEMA = "kb_chat_complexity_cache_v1"
_COMPLEXITY_CACHE_KEY_PREFIX = "complexity"


def _get_last_human(messages: list[Any]) -> HumanMessage | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


def _extract_user_input(state: dict) -> str:
    user_input = state.get("user_input")
    if isinstance(user_input, str) and user_input.strip():
        return user_input

    messages = state.get("messages")
    if isinstance(messages, list):
        last_human = _get_last_human(messages)
        if last_human is not None:
            content = getattr(last_human, "content", None)
            if isinstance(content, str):
                return content
    return ""


def _cache_kb_scope(kb_ids: list[str]) -> str:
    normalized = sorted(str(k).strip() for k in kb_ids if isinstance(k, str) and str(k).strip())
    if not normalized:
        return "kb_all"
    digest = hashlib.sha1(",".join(normalized).encode("utf-8")).hexdigest()[:12]
    return f"kb_{digest}"


def _complexity_cache_namespace(
    state: dict,
    runtime: Runtime[Any] | None = None,
) -> tuple[str, ...]:
    context = _runtime_context(runtime) if runtime is not None else {}
    memory_keys = state.get("memory_keys")
    memory = memory_keys if isinstance(memory_keys, dict) else {}
    thread_id = str(context.get("thread_id") or memory.get("thread_id") or "").strip()
    user_id = resolve_kb_chat_store_user_id(
        user_id=context.get("user_id") or memory.get("user_id"),
        thread_id=thread_id,
    )
    kb_ids_raw = context.get("kb_ids")
    if not isinstance(kb_ids_raw, list):
        kb_ids_raw = memory.get("kb_ids")
    kb_ids = kb_ids_raw if isinstance(kb_ids_raw, list) else []
    kb_ids_str = [str(k).strip() for k in kb_ids if isinstance(k, str) and str(k).strip()]
    return ("kb_chat", "complexity_cache", user_id, _cache_kb_scope(kb_ids_str))


def _complexity_cache_key(
    *,
    query: str,
    recall_risk: str,
    has_multi_target: bool,
    is_comparison: bool,
    decision_version: str,
) -> str:
    payload = {
        "query": query.strip(),
        "recall_risk": recall_risk.strip().lower(),
        "has_multi_target": bool(has_multi_target),
        "is_comparison": bool(is_comparison),
        "decision_version": decision_version.strip() or "kb_chat_complexity_classify_v4",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{_COMPLEXITY_CACHE_KEY_PREFIX}:{digest}"


def _wrap_cache_with_ttl(payload: dict[str, Any], *, ttl_seconds: int) -> dict[str, Any]:
    created_at = now_iso()
    return {
        "schema": _COMPLEXITY_CACHE_SCHEMA,
        "created_at": created_at,
        "ttl_seconds": int(ttl_seconds),
        "expires_ts": int(time.time()) + int(ttl_seconds),
        "payload": payload,
    }


def _unwrap_complexity_cache(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("schema") != _COMPLEXITY_CACHE_SCHEMA:
        return None
    expires_ts = raw.get("expires_ts")
    if isinstance(expires_ts, (int, float)) and int(expires_ts) > 0:
        if int(time.time()) >= int(expires_ts):
            return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload


async def _read_complexity_cache(
    *,
    state: dict,
    runtime: Runtime[Any] | None,
    cache_key: str,
) -> dict[str, Any] | None:
    if runtime is None or runtime.store is None:
        return None
    item = await runtime.store.aget(_complexity_cache_namespace(state, runtime), cache_key)
    if item is None:
        return None
    value = getattr(item, "value", None)
    if not isinstance(value, dict):
        return None
    return _unwrap_complexity_cache(value)


async def _write_complexity_cache(
    *,
    state: dict,
    runtime: Runtime[Any] | None,
    cache_key: str,
    ttl_seconds: int,
    payload: dict[str, Any],
) -> None:
    if runtime is None or runtime.store is None:
        return
    ns = _complexity_cache_namespace(state, runtime)
    wrapped = _wrap_cache_with_ttl(payload, ttl_seconds=ttl_seconds)
    if runtime.store.supports_ttl:
        await runtime.store.aput(ns, cache_key, wrapped, ttl=float(max(0, ttl_seconds)))
    else:
        await runtime.store.aput(ns, cache_key, wrapped)


def _normalize_meta_aliases(state: dict) -> list[str]:
    meta = state.get("normalized_meta")
    if not isinstance(meta, dict):
        return []
    aliases = meta.get("aliases")
    if not isinstance(aliases, list):
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if not isinstance(alias, str):
            continue
        value = alias.strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        deduped.append(value)
        seen.add(key)
    return deduped


def _dedupe_string_list(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _runtime_context(runtime: Runtime[Any]) -> dict[str, Any]:
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        return context
    return {}


def _safe_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _safe_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _resolve_prepare_strategy(state: dict[str, Any]) -> str:
    strategy_raw = state.get("query_strategy")
    strategy = str(strategy_raw).strip() if isinstance(strategy_raw, str) else ""
    if not strategy:
        decomposition_plan = _as_dict(state.get("decomposition_plan")) or {}
        strategy = str(decomposition_plan.get("strategy") or "").strip()
    if strategy not in {"direct", "decomposition", "multi_query"}:
        return "direct"
    return strategy


def _resolve_prepare_budget(
    *,
    state: dict[str, Any],
    runtime: Runtime[Any],
    settings: Settings,
) -> dict[str, Any]:
    context = _runtime_context(runtime)
    context_budget = _as_dict(context.get("message_budget")) or {}
    max_candidates = _safe_int(
        context_budget.get("max_candidates"),
        default=parallel_retrieval_max_branches(state, settings, runtime=runtime),
    )
    min_queries = _safe_int(
        context_budget.get("min_queries"),
        default=parallel_retrieval_min_queries(state, settings, runtime=runtime),
    )
    quality_threshold = _safe_float(
        context_budget.get("quality_threshold"),
        default=0.52,
    )
    include_main = context_budget.get("include_main")
    if not isinstance(include_main, bool):
        include_main = parallel_retrieval_include_main(state, settings, runtime=runtime)
    return {
        "max_candidates": max(1, min(max_candidates, 16)),
        "min_queries": max(1, min(min_queries, 8)),
        "quality_threshold": max(0.0, min(quality_threshold, 1.0)),
        "include_main": include_main,
    }


def _prepare_quality_score(item: dict[str, Any], *, strategy: str) -> float:
    kind = str(item.get("kind") or "other").strip() or "other"
    query = str(item.get("query") or "").strip()
    if not query:
        return 0.0

    base = {
        "main": 1.0,
        "subquery": 0.92,
        "variant": 0.84,
        "hyde": 0.74,
        "rewrite": 0.78,
        "other": 0.72,
    }.get(kind, 0.68)

    length = len(query)
    if length < 4:
        base -= 0.28
    elif length < 8:
        base -= 0.08
    elif length > 180:
        base -= 0.12

    if strategy == "decomposition" and kind == "subquery":
        base += 0.05
    if strategy == "multi_query" and kind == "variant":
        base += 0.04
    if kind == "hyde":
        hyde_queries = item.get("hyde_queries")
        if isinstance(hyde_queries, list) and len(hyde_queries) > 1:
            base += 0.02

    if isinstance(item.get("purpose"), str) and str(item.get("purpose")).strip():
        base += 0.02
    raw_tags = item.get("coverage_tags")
    if isinstance(raw_tags, list) and any(
        isinstance(tag, str) and str(tag).strip() for tag in raw_tags
    ):
        base += 0.03

    return round(max(0.0, min(base, 1.0)), 4)


def _merge_stage_summary(
    state: dict, key: str, summary: dict[str, Any], *, settings: Settings
) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    safe_summary = ensure_json_safe(
        summary, settings=settings, label=f"stage_summaries.{key}"
    )
    merged = {**stage_summaries, key: safe_summary}
    merged = ensure_json_safe(merged, settings=settings, label="stage_summaries")
    return merged


def _latest_summary_message(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, SystemMessage):
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.startswith("对话摘要："):
                return content
    return ""


def _strip_summary_prefix(summary: str) -> str:
    text = summary.strip()
    if text.startswith("对话摘要："):
        text = text[len("对话摘要：") :].strip()
    return text


def _recent_dialogue(messages: list[Any], *, max_turns: int = 3) -> str:
    """Fallback conversational context when no explicit summary is present."""
    lines: list[str] = []
    for msg in reversed(messages):
        role = None
        if isinstance(msg, HumanMessage):
            role = "用户"
        elif isinstance(msg, AIMessage):
            role = "助手"
        else:
            continue
        content = getattr(msg, "content", "")
        text = content if isinstance(content, str) else str(content)
        text = text.strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
        if len(lines) >= max_turns * 2:
            break
    lines.reverse()
    if not lines:
        return ""
    return "最近对话：\n" + "\n".join(lines)


def _normalize_for_compare(text: str) -> str:
    return " ".join(text.split()).strip()


def _recent_turns(messages: list[Any], *, max_turns: int = 3) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for msg in reversed(messages):
        role = None
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            continue
        content = getattr(msg, "content", "")
        text = content if isinstance(content, str) else str(content)
        text = text.strip()
        if not text:
            continue
        turns.append({"role": role, "text": text})
        if len(turns) >= max_turns * 2:
            break
    turns.reverse()
    return turns


def _render_display_context(
    *,
    summary: str,
    turns: list[dict[str, str]],
    memory_snippet: str,
    question: str,
) -> str:
    parts: list[str] = []
    normalized_question = _normalize_for_compare(question)
    if summary:
        parts.append(summary)
    elif turns:
        lines: list[str] = []
        for turn in turns:
            role = "用户" if turn.get("role") == "user" else "助手"
            text = turn.get("text", "").strip()
            if text:
                if role == "用户" and _normalize_for_compare(text) == normalized_question:
                    continue
                lines.append(f"{role}: {text}")
        if lines:
            parts.append("最近对话：\n" + "\n".join(lines))
    if memory_snippet:
        parts.append(memory_snippet)
    if normalized_question:
        parts.append(f"用户问题：{question.strip()}")
    return "\n\n".join(part for part in parts if part).strip()


def _turns_to_langchain_messages(turns: list[dict[str, str]]) -> list[Any]:
    lc_messages: list[Any] = []
    for turn in turns:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        if turn.get("role") == "user":
            lc_messages.append(HumanMessage(content=text))
        elif turn.get("role") == "assistant":
            lc_messages.append(AIMessage(content=text))
    return lc_messages


def _extract_summary_text(result: object) -> str:
    running = getattr(result, "running_summary", None)
    if running is not None:
        text = getattr(running, "summary", None) or getattr(running, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

    messages = getattr(result, "messages", None)
    if isinstance(messages, list) and messages:
        first = messages[0]
        content = getattr(first, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


async def _generate_summary_from_turns(
    *, turns: list[dict[str, str]], settings: Settings
) -> str:
    if not turns:
        return ""
    lc_messages = _turns_to_langchain_messages(turns)[-12:]
    if not lc_messages:
        return ""
    try:
        from langmem.short_term import summarize_messages
    except Exception:  # pragma: no cover
        return ""

    try:
        model = create_chat_model(settings=settings)
        summary_model = model.bind(max_tokens=settings.summary_max_tokens)
        token_counter = getattr(model, "get_num_tokens_from_messages", None)
        if token_counter is None:

            def token_counter(msgs: list[object]) -> int:
                return sum(
                    count_tokens_approximately(getattr(m, "content", "") or "")
                    for m in msgs
                )
    except Exception:  # pragma: no cover
        return ""

    def _run() -> object:
        return summarize_messages(
            lc_messages,
            running_summary=None,
            token_counter=token_counter,
            model=summary_model,
            max_tokens=settings.summary_max_tokens,
            max_tokens_before_summary=0,
            max_summary_tokens=settings.summary_max_tokens,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception:  # pragma: no cover
        return ""
    return _extract_summary_text(result)


def _select_turns_for_merge(
    turns: list[dict[str, str]], *, question: str, has_summary: bool
) -> list[dict[str, str]]:
    if not turns:
        return []
    normalized_question = _normalize_for_compare(question)
    selected: list[dict[str, str]] = []
    for turn in turns:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        if role == "user" and _normalize_for_compare(text) == normalized_question:
            continue
        selected.append({"role": role or "assistant", "text": text})
    if not selected:
        return []
    max_turns = 2 if has_summary else 4
    return selected[-max_turns * 2 :]


def _needs_conflict_resolution(*, summary_text: str, memory_snippet: str) -> bool:
    if not summary_text or not memory_snippet:
        return False
    summary_numbers = set(re.findall(r"\d+", summary_text))
    memory_numbers = set(re.findall(r"\d+", memory_snippet))
    return bool(summary_numbers and memory_numbers and summary_numbers.isdisjoint(memory_numbers))


async def merge_context(
    state: dict,
    runtime: Runtime[Any],
    settings: Settings,
) -> dict[str, Any]:
    """Merge summary/memory/user_input into `merged_context` (skeleton).

    Current implementation uses user_input + optional summary system message.
    """
    start = time.perf_counter()
    updates: dict[str, Any] = {}

    # Budget metadata is stored in metrics for checkpointer friendliness.
    updates.update(ensure_budget_initialized(state, settings))

    messages = state.get("messages")
    if not isinstance(messages, list):
        messages = []

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

    memory_snippet = ""
    if settings.memory_enabled and runtime.store is not None:
        context = _runtime_context(runtime)
        keys = (
            state.get("memory_keys")
            if isinstance(state.get("memory_keys"), dict)
            else {}
        )
        thread_id = str(context.get("thread_id") or keys.get("thread_id") or "").strip()
        user_id = resolve_kb_chat_store_user_id(
            user_id=context.get("user_id") or keys.get("user_id"),
            thread_id=thread_id,
        )
        kb_ids_raw = context.get("kb_ids")
        if not isinstance(kb_ids_raw, list):
            kb_ids_raw = keys.get("kb_ids") if isinstance(keys.get("kb_ids"), list) else []
        kb_ids = [str(k) for k in kb_ids_raw if isinstance(k, str) and k.strip()]
        try:
            mem = await aget_kb_chat_memory(
                store=runtime.store,
                user_id=user_id,
                thread_id=thread_id,
                kb_ids=kb_ids,
            )
            if mem:
                memory_snippet = render_kb_chat_memory_snippet(mem)
        except Exception:  # pragma: no cover
            memory_snippet = ""

    question = user_input.strip()
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
    if _needs_conflict_resolution(summary_text=summary_text, memory_snippet=memory_snippet):
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

    memory_for_render = memory_snippet if keep_memory else ""
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
        + len(memory_snippet)
        + len(question)
    )
    compression_ratio = round(len(merged) / source_chars, 4) if source_chars else 1.0

    stage_summaries = _merge_stage_summary(
        state,
        "merge_context",
        {
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "memory_included": bool(memory_for_render),
            "input_source": "user_input",
            "input_chars": len(question),
            "output_chars": len(merged),
            "summary_source": summary_source,
            "turns_seen": len(turns),
            "turns_selected": len(selected_turns),
            "compression_ratio": compression_ratio,
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


async def coref_rewrite(state: dict, settings: Settings) -> dict[str, Any]:
    """Coreference resolution / rewrite (degrades to original query on failure)."""
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
    selected_turns = (
        context_data.get("selected_turns")
        if isinstance(context_data.get("selected_turns"), list)
        else []
    )
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
        result = await svc.coref_rewrite(
            query,
            enabled=True,
            timeout_seconds=0,
            recent_turns=[
                item
                for item in selected_turns
                if isinstance(item, dict)
                and isinstance(item.get("role"), str)
                and isinstance(item.get("text"), str)
            ],
            summary_text=summary_text,
            memory_snippet=memory_snippet,
        )
        rewritten = result.query
        reason = result.reason
        if isinstance(result.meta, dict):
            meta = result.meta
    except Exception:  # pragma: no cover
        # Absolute fallback: keep original query.
        rewritten = query
        reason = "error"
        meta = {
            "triggered": False,
            "confidence": 0.0,
            "candidate_count": 0,
            "selected_mention": "",
            "resolution_source": "none",
            "needs_clarification": False,
        }

    stage_summaries = _merge_stage_summary(
        state,
        "coref_rewrite",
        {
            "rewritten": rewritten != query,
            "reason": reason,
            "input_source": input_source,
            "input_chars": len(query.strip()),
            "output_chars": len(rewritten.strip()),
            "changed_ratio": (
                round(abs(len(rewritten.strip()) - len(query.strip())) / len(query.strip()), 4)
                if query.strip()
                else 0.0
            ),
            "triggered": bool(meta.get("triggered")),
            "confidence": float(meta.get("confidence") or 0.0),
            "candidate_count": int(meta.get("candidate_count") or 0),
            "selected_mention": str(meta.get("selected_mention") or ""),
            "resolution_source": str(meta.get("resolution_source") or "none"),
            "needs_clarification_hint": bool(meta.get("needs_clarification")),
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )

    return {
        "coref_query": rewritten,
        "coref_meta": meta,
        "stage_summaries": stage_summaries,
    }


async def ambiguity_check(state: dict, settings: Settings) -> dict[str, Any]:
    """Ambiguity check with model-first decision and structured clarification payload."""
    start = time.perf_counter()
    query = state.get("coref_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    ambiguous = False
    reverse_question = ""
    reason: str | None = None
    reason_code: str | None = None
    confidence: float | None = None
    model_reason: str | None = None
    fallback_used = False
    clarification_payload: dict[str, Any] | None = None

    coref_meta = state.get("coref_meta")
    try:
        svc = QueryRewriteService(settings=settings)
        timeout_seconds = float(
            getattr(settings, "kb_chat_ambiguity_timeout_seconds", 0.5)
        )
        result = await svc.ambiguity_check(
            query,
            enabled=True,
            timeout_seconds=timeout_seconds,
            coref_meta=coref_meta if isinstance(coref_meta, dict) else None,
        )
        ambiguous = result.ambiguous
        reverse_question = result.reverse_question or ""
        reason = result.reason
        reason_code = result.reason_code
        confidence = result.confidence
        model_reason = result.model_reason
        fallback_used = bool(result.fallback_used)
        if isinstance(result.clarification_payload, dict):
            clarification_payload = result.clarification_payload
    except Exception:  # pragma: no cover
        ambiguous = False
        reverse_question = ""
        reason = "error"
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
    state: dict,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Normalize query with rule+LLM strategy and retrieval-safe metadata."""
    start = time.perf_counter()
    input_source = "coref_query"
    query = state.get("coref_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
        input_source = "user_input"

    rewritten = query
    rewritten_flag = False
    normalization_source = "rule_fallback"
    fallback_reason = "error"
    normalized_meta: dict[str, Any] = {
        "source": "rule_fallback",
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
        result = await svc.normalize_rewrite(
            query,
            llm_enabled=True,
            alias_limit=normalize_alias_max(state, settings, runtime=runtime),
            timeout_seconds=normalize_timeout_seconds(state, settings, runtime=runtime),
        )
        rewritten = result.query
        rewritten_flag = result.rewritten
        if isinstance(result.meta, dict):
            normalized_meta = {**normalized_meta, **result.meta}
        normalization_source = str(normalized_meta.get("source") or "rule_fallback")
        fallback_reason = str(normalized_meta.get("fallback_reason") or result.reason or "")
    except Exception:  # pragma: no cover
        rewritten = query
        rewritten_flag = False

    normalized_aliases = (
        normalized_meta.get("aliases") if isinstance(normalized_meta.get("aliases"), list) else []
    )

    stage_summaries = _merge_stage_summary(
        state,
        "normalize_rewrite",
        {
            "rewritten": rewritten_flag,
            "normalization_source": normalization_source,
            "fallback_reason": fallback_reason,
            "alias_count": len([a for a in normalized_aliases if isinstance(a, str) and a.strip()]),
            "constraint_preserved": bool(normalized_meta.get("constraint_preserved", True)),
            "drift_risk": bool(normalized_meta.get("drift_risk", False)),
            "recall_risk": str(normalized_meta.get("recall_risk") or "medium"),
            "input_source": input_source,
            "input_chars": len(query.strip()),
            "output_chars": len(rewritten.strip()),
            "changed_ratio": (
                round(abs(len(rewritten.strip()) - len(query.strip())) / len(query.strip()), 4)
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


async def complexity_classify(
    state: dict,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> Command[str]:
    """Decide preprocess strategy: direct / decomposition / multi-query."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    strategy = "direct"
    success = False
    reasoning: str | None = None
    confidence = 0.0
    risk_flags: list[str] = []
    decision_version = "kb_chat_complexity_classify_v4"
    cache_hit = False
    cache_status = "disabled"
    cache_key_version = "v1"
    normalized_meta = state.get("normalized_meta")
    if not isinstance(normalized_meta, dict):
        normalized_meta = {}
    recall_risk = str(normalized_meta.get("recall_risk") or "unknown")
    has_multi_target = bool(normalized_meta.get("has_multi_target"))
    is_comparison = bool(normalized_meta.get("is_comparison"))
    cache_enabled = bool(getattr(settings, "kb_chat_complexity_cache_enabled", True))
    cache_key = _complexity_cache_key(
        query=query,
        recall_risk=recall_risk,
        has_multi_target=has_multi_target,
        is_comparison=is_comparison,
        decision_version=decision_version,
    )
    if cache_enabled:
        if runtime is None or runtime.store is None:
            cache_status = "no_store"
        else:
            try:
                cached = await _read_complexity_cache(
                    state=state,
                    runtime=runtime,
                    cache_key=cache_key,
                )
            except Exception:  # pragma: no cover
                cached = None
                cache_status = "read_error"
            if isinstance(cached, dict):
                candidate_strategy = str(cached.get("strategy") or "direct").strip().lower()
                strategy = (
                    candidate_strategy
                    if candidate_strategy in {"direct", "decomposition", "multi_query"}
                    else "direct"
                )
                success = bool(cached.get("success"))
                reasoning = str(cached.get("reasoning") or "").strip() or None
                confidence = round(
                    max(0.0, min(1.0, float(cached.get("confidence") or 0.0))),
                    4,
                )
                decision_version = str(
                    cached.get("decision_version") or "kb_chat_complexity_classify_v4"
                ).strip() or "kb_chat_complexity_classify_v4"
                raw_flags = (
                    cached.get("risk_flags")
                    if isinstance(cached.get("risk_flags"), list)
                    else []
                )
                risk_flags = [
                    str(flag).strip()
                    for flag in raw_flags
                    if isinstance(flag, str) and flag.strip()
                ][:8]
                cache_hit = True
                cache_status = "hit"
            elif cache_status not in {"read_error"}:
                cache_status = "miss"

    if not cache_hit:
        try:
            svc = QueryRewriteService(settings=settings)
            decision = await svc.classify_complexity(
                query,
                recall_risk=recall_risk,
                has_multi_target=has_multi_target,
                is_comparison=is_comparison,
                timeout_seconds=float(
                    getattr(settings, "kb_chat_complexity_model_timeout_seconds", 1.5)
                ),
            )
            strategy = (
                decision.strategy
                if decision.strategy in {"direct", "decomposition", "multi_query"}
                else "direct"
            )
            success = decision.success
            reasoning = decision.reasoning
            confidence = round(max(0.0, min(1.0, float(decision.confidence or 0.0))), 4)
            decision_version = str(
                decision.decision_version or "kb_chat_complexity_classify_v4"
            ).strip()
            if not decision_version:
                decision_version = "kb_chat_complexity_classify_v4"
            raw_flags = (
                decision.risk_flags
                if isinstance(decision.risk_flags, list)
                else []
            )
            risk_flags = [
                str(flag).strip()
                for flag in raw_flags
                if isinstance(flag, str) and flag.strip()
            ][:8]
        except Exception:  # pragma: no cover
            strategy = "direct"
            success = False
        if cache_enabled and success:
            try:
                await _write_complexity_cache(
                    state=state,
                    runtime=runtime,
                    cache_key=cache_key,
                    ttl_seconds=max(
                        0, int(getattr(settings, "kb_chat_complexity_cache_ttl_seconds", 120))
                    ),
                    payload={
                        "strategy": strategy,
                        "success": success,
                        "reasoning": reasoning,
                        "confidence": confidence,
                        "risk_flags": risk_flags,
                        "decision_version": decision_version,
                    },
                )
                if cache_status == "miss":
                    cache_status = "write_through"
            except Exception:  # pragma: no cover
                if cache_status in {"miss", "no_store", "disabled"}:
                    cache_status = "write_error"

    route_map = {
        "decomposition": "decomposition",
        "multi_query": "generate_variants",
        "direct": "prepare_messages",
    }
    goto = route_map.get(strategy, route_map["direct"])

    stage_summaries = _merge_stage_summary(
        state,
        "complexity_classify",
        {
            "strategy": strategy,
            "confidence": confidence,
            "risk_flags": risk_flags,
            "decision_version": decision_version,
            "recall_risk": recall_risk,
            "has_multi_target": has_multi_target,
            "is_comparison": is_comparison,
            "reasoning": reasoning,
            "success": success,
            "goto": goto,
            "cache_hit": cache_hit,
            "complexity_cache_status": cache_status,
            "cache_key_version": cache_key_version,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    # Reset fan-out artifacts before entering the selected branch.
    updates: dict[str, Any] = {
        "query_strategy": strategy,
        "query_strategy_confidence": confidence,
        "query_strategy_signals": risk_flags,
        "sub_queries": [],
        "multi_queries": [],
        "decomposition_plan": {
            "strategy": "direct",
            "version": "kb_chat_decomposition_plan_v2",
            "sub_query_specs": [],
            "risk_flags": [],
            "reasoning": "",
        },
        "stage_summaries": stage_summaries,
    }
    return Command(update=updates, goto=goto)


async def decomposition(state: dict, settings: Settings) -> dict[str, Any]:
    """Generate sub-queries (via QueryRewriteService; degrades safely)."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    sub_queries: list[str] = []
    success = False
    reason: str | None = None
    decomposition_plan: dict[str, Any] = {
        "strategy": "direct",
        "version": "kb_chat_decomposition_plan_v2",
        "sub_query_specs": [],
        "risk_flags": [],
        "reasoning": "",
    }
    diagnostics: dict[str, Any] = {}
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.decompose(query)
        sub_queries = result.queries
        success = result.success
        reason = result.reason
        if isinstance(result.plan, dict):
            decomposition_plan = result.plan
        if isinstance(result.diagnostics, dict):
            diagnostics = result.diagnostics
    except Exception:  # pragma: no cover
        sub_queries = [query.strip()] if query.strip() else []
        success = False
        reason = "error"
        decomposition_plan = {
            "strategy": "direct",
            "version": "kb_chat_decomposition_plan_v2",
            "sub_query_specs": [
                {
                    "query": query.strip(),
                    "priority": 1,
                    "coverage_tags": [],
                    "purpose": "exception_fallback",
                }
            ]
            if query.strip()
            else [],
            "risk_flags": ["error_fallback"],
            "reasoning": "error",
        }

    stage_summaries = _merge_stage_summary(
        state,
        "decomposition",
        {
            "driver": "llm",
            "count": len(sub_queries),
            "success": success,
            "reason": reason,
            "strategy": decomposition_plan.get("strategy"),
            "version": decomposition_plan.get("version"),
            "risk_flags": decomposition_plan.get("risk_flags"),
            "diagnostics": diagnostics,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    return {
        "sub_queries": sub_queries,
        "decomposition_plan": decomposition_plan,
        "stage_summaries": stage_summaries,
    }

async def generate_variants(state: dict, settings: Settings) -> dict[str, Any]:
    """Generate query variants (via QueryRewriteService; degrades safely)."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
    deduped: list[str] = []
    alias_candidates = _normalize_meta_aliases(state)
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.generate_variants(query)
        deduped = result.queries
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        deduped = [query.strip()] if query.strip() else []
        success = False
        reason = "error"
    if alias_candidates:
        deduped = [*deduped, *alias_candidates]
        # dedupe keep order
        seen: set[str] = set()
        merged_variants: list[str] = []
        for item in deduped:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value or value.casefold() in seen:
                continue
            merged_variants.append(value)
            seen.add(value.casefold())
        deduped = merged_variants

    stage_summaries = _merge_stage_summary(
        state,
        "generate_variants",
        {
            "driver": "llm",
            "count": len(deduped),
            "alias_count": len(alias_candidates),
            "success": success,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"multi_queries": deduped, "stage_summaries": stage_summaries}


async def entity_expand(
    state: dict,
    runtime: Runtime[Any],
    settings: Settings,
) -> Command[str]:
    """Entity expansion with confidence/drift guardrails and Command routing."""
    start = time.perf_counter()
    _ = runtime
    queries = state.get("multi_queries")
    if not isinstance(queries, list):
        queries = []
    original = [q for q in queries if isinstance(q, str) and q.strip()]
    alias_candidates = _normalize_meta_aliases(state)
    normalized_query = state.get("normalized_query")
    if not isinstance(normalized_query, str):
        normalized_query = ""
    normalized_meta = state.get("normalized_meta")
    entities = []
    if isinstance(normalized_meta, dict) and isinstance(normalized_meta.get("entities"), list):
        entities = [item for item in normalized_meta["entities"] if isinstance(item, str)]

    max_candidates = entity_expand_max_candidates(state, settings, runtime=runtime)
    max_variants = entity_expand_max_variants(state, settings, runtime=runtime)
    min_confidence = entity_expand_min_confidence(state, settings, runtime=runtime)
    timeout_seconds = entity_expand_timeout_seconds(state, settings, runtime=runtime)

    expanded = original
    success = False
    reason: str | None = "disabled"
    diagnostics: dict[str, Any] = {}
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.entity_expand(
            original,
            normalized_query=normalized_query,
            aliases=alias_candidates,
            entities=entities,
            enabled=True,
            max_candidates=max_candidates,
            max_variants=max_variants,
            min_confidence=min_confidence,
            timeout_seconds=timeout_seconds,
        )
        expanded = result.queries
        success = result.success
        reason = result.reason
        diagnostics = (
            result.diagnostics if isinstance(result.diagnostics, dict) else {}
        )
    except Exception:  # pragma: no cover
        expanded = original
        reason = "error"
        success = False
        diagnostics = {"fallback_reason": "exception"}
    if alias_candidates:
        expanded = [*expanded, *alias_candidates]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in expanded:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value or value.casefold() in seen:
                continue
            deduped.append(value)
            seen.add(value.casefold())
        expanded = deduped
    expanded = [value for value in expanded if isinstance(value, str) and value.strip()]
    expanded = expanded[:max(1, max_variants)]
    input_count = len(_dedupe_string_list(original))
    expanded_count = len(_dedupe_string_list(expanded))
    added_count = max(0, expanded_count - min(input_count, max(1, max_variants)))
    pruned_count = int(diagnostics.get("pruned_count") or 0)
    pruned_drift = int(diagnostics.get("pruned_drift") or 0)
    fallback_reason = (
        str(diagnostics.get("fallback_reason")).strip()
        if isinstance(diagnostics.get("fallback_reason"), str)
        else ""
    )
    entity_expand_meta = {
        "enabled": True,
        "input_count": input_count,
        "expanded_count": expanded_count,
        "added_count": added_count,
        "pruned_count": pruned_count,
        "pruned_drift": pruned_drift,
        "pruned_low_confidence": int(diagnostics.get("pruned_low_confidence") or 0),
        "min_confidence": min_confidence,
        "max_candidates": max_candidates,
        "max_variants": max_variants,
        "reason": reason,
        "fallback_reason": fallback_reason or reason,
        "drift_guardrail_triggered": pruned_drift > 0,
    }
    stage_summaries = _merge_stage_summary(
        state,
        "entity_expand",
        {
            "success": success,
            "enabled": True,
            "reason": reason,
            "input_count": input_count,
            "expanded_count": expanded_count,
            "added_count": added_count,
            "pruned_count": pruned_count,
            "pruned_low_confidence": int(diagnostics.get("pruned_low_confidence") or 0),
            "pruned_drift": pruned_drift,
            "drift_guardrail_triggered": pruned_drift > 0,
            "fallback_reason": fallback_reason or reason,
            "count": expanded_count,
            "min_confidence": min_confidence,
            "alias_count": len(alias_candidates),
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return Command(
        update={
            "multi_queries": expanded,
            "entity_expand_meta": entity_expand_meta,
            "stage_summaries": stage_summaries,
        },
        goto="hyde",
    )


async def hyde(state: dict, settings: Settings) -> dict[str, Any]:
    """HyDE node (LLM-driven with safe fallback)."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
    hyde_docs: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.hyde(query, enabled=True)
        hyde_docs = [item for item in result.queries if isinstance(item, str) and item.strip()]
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        hyde_docs = []
        success = False
        reason = "error"
    loop_counts = state.get("loop_counts")
    retry_regenerated = (
        isinstance(loop_counts, dict) and int(loop_counts.get("retrieval_retries") or 0) > 0
    )

    stage_summaries = _merge_stage_summary(
        state,
        "hyde",
        {
            "driver": "llm",
            "enabled": True,
            "success": success,
            "requested_count": HYDE_NUM_HYPOTHESES,
            "generated_count": len(hyde_docs),
            "retry_regenerated": retry_regenerated,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"hyde_docs": hyde_docs, "stage_summaries": stage_summaries}


async def prepare_messages(
    state: dict,
    runtime: Runtime[Any],
    settings: Settings,
) -> Command[str]:
    """Assemble retrieval query bundle and route with Command.

    This node keeps message/query planning explicit for observability:
    - message_plan: candidate scoring + budget decisions
    - query_bundle: selected query_items + dedupe statistics
    - prepare_diagnostics: quality signals + fallback reason
    """

    start = time.perf_counter()
    normalized = state.get("normalized_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = _extract_user_input(state)
    normalized = normalized.strip()

    original_query = state.get("coref_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = state.get("rewrite_input_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = _extract_user_input(state)
    original_query = original_query.strip() or normalized

    sub_queries_raw = state.get("sub_queries")
    if not isinstance(sub_queries_raw, list):
        sub_queries_raw = []
    sub_queries = [q for q in sub_queries_raw if isinstance(q, str) and q.strip()]

    decomposition_plan = state.get("decomposition_plan")
    if not isinstance(decomposition_plan, dict):
        decomposition_plan = {}
    sub_query_specs_raw = decomposition_plan.get("sub_query_specs")
    if not isinstance(sub_query_specs_raw, list):
        sub_query_specs_raw = []
    sub_query_specs = [spec for spec in sub_query_specs_raw if isinstance(spec, dict)]

    multi_queries_raw = state.get("multi_queries")
    if not isinstance(multi_queries_raw, list):
        multi_queries_raw = []
    multi_queries = [
        query for query in multi_queries_raw if isinstance(query, str) and query.strip()
    ]

    alias_variants = _normalize_meta_aliases(state)
    hyde_docs_raw = state.get("hyde_docs")
    if not isinstance(hyde_docs_raw, list):
        hyde_docs_raw = []
    hyde_docs = [doc for doc in hyde_docs_raw if isinstance(doc, str) and doc.strip()]

    strategy = _resolve_prepare_strategy(state)
    budget = _resolve_prepare_budget(state=state, runtime=runtime, settings=settings)

    variant_seed = [
        query
        for query in (multi_queries or alias_variants)
        if isinstance(query, str) and query.strip()
    ]
    # O3: always keep original query as main item, then append normalized query.
    variant_candidates: list[str] = []
    if normalized and normalized.casefold() != original_query.casefold():
        variant_candidates.append(normalized)
    variant_candidates.extend(variant_seed)
    variant_candidates = _dedupe_string_list(variant_candidates)

    raw_items = build_query_items(
        main_query=original_query,
        sub_queries=sub_queries,
        sub_query_specs=sub_query_specs,
        variants=variant_candidates,
        hyde_docs=hyde_docs or None,
    )

    scored_rows: list[dict[str, Any]] = []
    for idx, raw_item in enumerate(raw_items):
        item = _as_dict(raw_item) or {}
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        kind = str(item.get("kind") or "other").strip() or "other"
        priority = item.get("priority")
        if not isinstance(priority, int):
            if kind == "main":
                priority = 1
            elif kind == "hyde":
                priority = 7
            else:
                priority = idx + 2
        source = "build_query_items"
        if kind == "subquery":
            source = "decomposition"
        elif kind == "variant":
            source = "multi_query"
        elif kind == "hyde":
            source = "hyde"

        scored_rows.append(
            {
                "index": idx,
                "kind": kind,
                "query": query,
                "source": source,
                "priority": max(1, min(int(priority), 8)),
                "quality_score": _prepare_quality_score(item, strategy=strategy),
                "item": item,
            }
        )

    deduped_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, bool, bool]] = set()
    for row in scored_rows:
        item = _as_dict(row.get("item")) or {}
        dedupe_key = (
            str(row.get("query") or "").casefold(),
            bool(item.get("use_dense", True)),
            bool(item.get("use_bm25", True)),
        )
        if dedupe_key in seen_keys:
            dropped_rows.append(
                {
                    "kind": row.get("kind"),
                    "query": row.get("query"),
                    "reason": "duplicate",
                }
            )
            continue
        seen_keys.add(dedupe_key)
        deduped_rows.append(row)

    quality_threshold = float(budget["quality_threshold"])
    filtered_rows: list[dict[str, Any]] = []
    for row in deduped_rows:
        score = float(row.get("quality_score") or 0.0)
        kind = str(row.get("kind") or "")
        if score < quality_threshold and kind != "main":
            dropped_rows.append(
                {
                    "kind": kind or "other",
                    "query": row.get("query"),
                    "reason": "low_quality",
                    "quality_score": score,
                }
            )
            continue
        filtered_rows.append(row)

    filtered_rows = sorted(
        filtered_rows,
        key=lambda row: (
            0 if str(row.get("kind") or "") == "main" else 1,
            int(row.get("priority") or 99),
            -float(row.get("quality_score") or 0.0),
            int(row.get("index") or 0),
        ),
    )

    max_candidates = int(budget["max_candidates"])
    selected_rows: list[dict[str, Any]] = []
    for row in filtered_rows:
        if len(selected_rows) >= max_candidates:
            dropped_rows.append(
                {
                    "kind": row.get("kind"),
                    "query": row.get("query"),
                    "reason": "over_budget",
                }
            )
            continue
        selected_rows.append(row)

    include_main = bool(budget["include_main"])
    if include_main and not any(
        str(row.get("kind") or "") == "main" for row in selected_rows
    ):
        main_row = next(
            (
                row
                for row in filtered_rows
                if str(row.get("kind") or "") == "main"
            ),
            None,
        )
        if main_row is not None:
            if len(selected_rows) >= max_candidates and selected_rows:
                removed = selected_rows.pop()
                dropped_rows.append(
                    {
                        "kind": removed.get("kind"),
                        "query": removed.get("query"),
                        "reason": "replace_with_main",
                    }
                )
            selected_rows.insert(0, main_row)

    selected_items: list[dict[str, Any]] = []
    for row in selected_rows:
        item = _as_dict(row.get("item"))
        if item:
            selected_items.append(item)

    kind_breakdown: dict[str, int] = {}
    for item in selected_items:
        kind = str(item.get("kind") or "other").strip() or "other"
        kind_breakdown[kind] = int(kind_breakdown.get(kind, 0)) + 1

    fallback_reason = "none"
    if not selected_items:
        fallback_reason = (
            "all_filtered_low_quality" if deduped_rows else "empty_query_bundle"
        )
    elif strategy != "direct" and len(selected_items) < int(budget["min_queries"]):
        fallback_reason = "below_min_queries"

    quality_signals: list[str] = []
    if any(str(row.get("kind")) == "subquery" for row in scored_rows):
        quality_signals.append("has_subqueries")
    if any(str(row.get("kind")) == "variant" for row in scored_rows):
        quality_signals.append("has_variants")
    if any(str(row.get("kind")) == "hyde" for row in scored_rows):
        quality_signals.append("has_hyde")
    if any(str(item.get("reason")) == "duplicate" for item in dropped_rows):
        quality_signals.append("dedup_applied")
    if any(str(item.get("reason")) == "low_quality" for item in dropped_rows):
        quality_signals.append("quality_filtered")
    if any(str(item.get("reason")) == "over_budget" for item in dropped_rows):
        quality_signals.append("budget_trimmed")
    if fallback_reason != "none":
        quality_signals.append(f"fallback:{fallback_reason}")

    message_plan = {
        "strategy": strategy,
        "candidates": [
            {
                "index": int(row.get("index") or 0),
                "kind": str(row.get("kind") or "other"),
                "query": str(row.get("query") or ""),
                "source": str(row.get("source") or "unknown"),
                "priority": int(row.get("priority") or 1),
                "quality_score": float(row.get("quality_score") or 0.0),
            }
            for row in scored_rows
        ],
        "selected": [
            {
                "index": int(row.get("index") or 0),
                "kind": str(row.get("kind") or "other"),
                "query": str(row.get("query") or ""),
                "source": str(row.get("source") or "unknown"),
                "priority": int(row.get("priority") or 1),
                "quality_score": float(row.get("quality_score") or 0.0),
            }
            for row in selected_rows
        ],
        "dropped": dropped_rows,
        "budget": {
            **budget,
            "candidate_count": len(scored_rows),
            "selected_count": len(selected_items),
        },
    }

    query_bundle = {
        "items": selected_items,
        "kind_breakdown": kind_breakdown,
        "dedup_stats": {
            "raw_count": len(scored_rows),
            "after_dedup_count": len(deduped_rows),
            "selected_count": len(selected_items),
            "dropped_count": len(dropped_rows),
            "duplicate_dropped": sum(
                1 for item in dropped_rows if str(item.get("reason")) == "duplicate"
            ),
            "low_quality_dropped": sum(
                1 for item in dropped_rows if str(item.get("reason")) == "low_quality"
            ),
        },
    }

    latency_ms = int((time.perf_counter() - start) * 1000)
    prepare_diagnostics = {
        "quality_signals": quality_signals,
        "fallback_reason": fallback_reason,
        "timing": {"latency_ms": latency_ms},
    }

    stage_summaries = _merge_stage_summary(
        state,
        "prepare_messages",
        {
            "message_plan": {
                "strategy": strategy,
                "candidate_count": len(scored_rows),
                "selected_count": len(selected_items),
                "dropped_count": len(dropped_rows),
                "original_query": original_query,
                "normalized_query": normalized,
                "budget": budget,
            },
            "query_bundle": {
                "items_count": len(selected_items),
                "kind_breakdown": kind_breakdown,
                "dedup_stats": query_bundle["dedup_stats"],
            },
            "diagnostics": {
                "quality_signals": quality_signals,
                "fallback_reason": fallback_reason,
                "latency_ms": latency_ms,
                "completed_at": now_iso(),
            },
        },
        settings=settings,
    )

    update: dict[str, Any] = {
        "query_items": selected_items,
        "query_bundle": query_bundle,
        "message_plan": message_plan,
        "prepare_diagnostics": prepare_diagnostics,
        "stage_summaries": stage_summaries,
    }

    goto = "dispatch_subqueries"
    if fallback_reason != "none":
        goto = "transform_query"
        reflection = _as_dict(state.get("reflection")) or {}
        update["reflection"] = {
            **reflection,
            "action": "transform_query",
            "reason": fallback_reason,
        }

    outer_next_node = "transform_query" if goto == "transform_query" else "retrieval_subgraph"
    update = {
        **update,
        **merge_routing_decision(
            state,
            "preprocess",
            {
                "phase": "preprocess",
                "next_node": outer_next_node,
                "action": "transform_query" if goto == "transform_query" else "none",
                "reason": fallback_reason if fallback_reason != "none" else "prepared",
                "reason_code": fallback_reason if fallback_reason != "none" else "prepared",
                "decision_source": "prepare_messages",
                "completed_at": now_iso(),
            },
            updates=update,
        ),
    }
    return Command(update=update, goto=goto)
