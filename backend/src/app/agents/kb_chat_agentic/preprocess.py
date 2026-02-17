"""KB Chat agentic preprocess nodes (MergeContext → HyDE).

These nodes are intentionally minimal first:
- Prefer safe no-op / heuristic behaviors
- Defer prompt-heavy LLM behaviors to later tasks (see OpenSpec tasks 1.4/1.11)
"""

from __future__ import annotations

import time
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.agents.kb_chat_memory import (
    aget_kb_chat_memory,
    render_kb_chat_memory_snippet,
)
from app.core.settings import Settings
from app.services.query_rewrite_service import QueryRewriteService, build_query_items

from .budget import (
    ensure_budget_initialized,
    now_iso,
)
from .json_safety import ensure_json_safe
from .runtime_config import (
    ambiguity_check_enabled,
    decomposition_enabled,
    hyde_enabled,
    multi_query_enabled,
    query_rewrite_enabled,
)


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
    summary = _latest_summary_message(messages)
    dialogue = "" if summary else _recent_dialogue(messages, max_turns=3)

    memory_snippet = ""
    if settings.memory_enabled and runtime.store is not None:
        keys = (
            state.get("memory_keys")
            if isinstance(state.get("memory_keys"), dict)
            else {}
        )
        user_id = str(keys.get("user_id") or "local")
        thread_id = str(keys.get("thread_id") or "unknown_thread")
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

    merged = user_input.strip()
    prefixes = [p for p in [summary, dialogue, memory_snippet] if p]
    if prefixes:
        merged = "\n\n".join([*prefixes, f"用户问题：{merged}"])

    stage_summaries = _merge_stage_summary(
        state,
        "merge_context",
        {
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "memory_included": bool(memory_snippet),
            "completed_at": now_iso(),
        },
        settings=settings,
    )

    return {
        **updates,
        "user_input": user_input,
        "merged_context": merged,
        "stage_summaries": stage_summaries,
    }


async def coref_rewrite(state: dict, settings: Settings) -> dict[str, Any]:
    """Coreference resolution / rewrite (degrades to original query on failure)."""
    start = time.perf_counter()
    query = state.get("merged_context")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    rewritten = query
    reason: str | None = None
    rewrite_enabled = query_rewrite_enabled(state, settings)
    if not rewrite_enabled:
        rewritten = query
        reason = "disabled"
    else:
        try:
            svc = QueryRewriteService(settings=settings)
            result = await svc.coref_rewrite(
                query,
                enabled=rewrite_enabled,
                timeout_seconds=0,
            )
            rewritten = result.query
            reason = result.reason
        except Exception:  # pragma: no cover
            # Absolute fallback: keep original query.
            rewritten = query
            reason = "error"

    stage_summaries = _merge_stage_summary(
        state,
        "coref_rewrite",
        {
            "rewritten": rewritten != query,
            "reason": reason,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )

    return {"coref_query": rewritten, "stage_summaries": stage_summaries}


async def ambiguity_check(state: dict, settings: Settings) -> dict[str, Any]:
    """Ambiguity check (heuristic-first).

    If ambiguous, set reflection.action=clarify and populate final_answer with a
    reverse question. (Current KB chat API does not support interrupt/resume.)
    """
    start = time.perf_counter()
    query = state.get("coref_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    ambiguous = False
    reverse_question = ""
    reason: str | None = None
    if ambiguity_check_enabled(state, settings):
        try:
            svc = QueryRewriteService(settings=settings)
            result = await svc.ambiguity_check(query, timeout_seconds=0)
            ambiguous = result.ambiguous
            reverse_question = result.reverse_question or ""
            reason = result.reason
        except Exception:  # pragma: no cover
            ambiguous = False
            reverse_question = ""
            reason = "error"

    stage_summaries = _merge_stage_summary(
        state,
        "ambiguity_check",
        {
            "ambiguous": ambiguous,
            "reason": reason,
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
        },
        "final_answer": reverse_question,
        "stage_summaries": stage_summaries,
    }


async def normalize_rewrite(state: dict, settings: Settings) -> dict[str, Any]:
    """Normalize query (skeleton: currently pass-through from coref_query)."""
    start = time.perf_counter()
    query = state.get("coref_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    rewritten = query
    rewritten_flag = False
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.normalize_rewrite(query)
        rewritten = result.query
        rewritten_flag = result.rewritten
    except Exception:  # pragma: no cover
        rewritten = query
        rewritten_flag = False

    stage_summaries = _merge_stage_summary(
        state,
        "normalize_rewrite",
        {
            "rewritten": rewritten_flag,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )
    return {"normalized_query": rewritten, "stage_summaries": stage_summaries}


def decomp_check_route(state: dict, settings: Settings) -> str:
    """Route: Decomposition enabled? (Decomposition and multi-query are mutually exclusive.)"""
    if decomposition_enabled(state, settings):
        return "decomposition"
    return "multi_query_check"


async def decomposition(state: dict, settings: Settings) -> dict[str, Any]:
    """Generate sub-queries (via QueryRewriteService; degrades safely)."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    sub_queries: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.decompose(
            query,
            enabled=decomposition_enabled(state, settings),
        )
        sub_queries = result.queries
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        sub_queries = [query.strip()] if query.strip() else []
        success = False
        reason = "error"

    stage_summaries = _merge_stage_summary(
        state,
        "decomposition",
        {
            "driver": "llm",
            "count": len(sub_queries),
            "success": success,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    return {"sub_queries": sub_queries, "stage_summaries": stage_summaries}


def multi_query_check_route(state: dict, settings: Settings) -> str:
    """Route: multi-query enabled? (skipped when decomposition is enabled)."""
    if multi_query_enabled(state, settings):
        return "generate_variants"
    return "hyde_check"


async def generate_variants(state: dict, settings: Settings) -> dict[str, Any]:
    """Generate query variants (via QueryRewriteService; degrades safely)."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
    deduped: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.generate_variants(
            query,
            enabled=multi_query_enabled(state, settings),
        )
        deduped = result.queries
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        deduped = [query.strip()] if query.strip() else []
        success = False
        reason = "error"

    stage_summaries = _merge_stage_summary(
        state,
        "generate_variants",
        {
            "driver": "llm",
            "count": len(deduped),
            "success": success,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"multi_queries": deduped, "stage_summaries": stage_summaries}


async def entity_expand(state: dict, settings: Settings) -> dict[str, Any]:
    """Entity expansion (placeholder; no-op for now)."""
    start = time.perf_counter()
    queries = state.get("multi_queries")
    if not isinstance(queries, list):
        queries = []

    expanded = queries
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.entity_expand([q for q in queries if isinstance(q, str)])
        expanded = result.queries
        reason = result.reason
    except Exception:  # pragma: no cover
        expanded = queries
        reason = "error"
    stage_summaries = _merge_stage_summary(
        state,
        "entity_expand",
        {
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"multi_queries": expanded, "stage_summaries": stage_summaries}


def hyde_check_route(state: dict, settings: Settings) -> str:
    if hyde_enabled(state, settings):
        return "hyde"
    return "prepare_messages"


async def hyde(state: dict, settings: Settings) -> dict[str, Any]:
    """HyDE node (LLM-driven with safe fallback)."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
    hyde_doc = ""
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        enabled = hyde_enabled(state, settings)
        result = await svc.hyde(query, enabled=enabled)
        hyde_doc = result.text
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        hyde_doc = ""
        success = False
        reason = "error"

    stage_summaries = _merge_stage_summary(
        state,
        "hyde",
        {
            "driver": "llm",
            "enabled": hyde_enabled(state, settings),
            "success": success,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"hyde_doc": hyde_doc, "stage_summaries": stage_summaries}


async def prepare_messages(state: dict, settings: Settings) -> dict[str, Any]:
    """Build query_items for downstream retrieval/reflection layers.

    Note: We intentionally do NOT inject extra SystemMessage hints into `messages` to avoid
    leaking internal artifacts to clients via message streaming.
    """
    start = time.perf_counter()
    messages = state.get("messages")
    if not isinstance(messages, list):
        messages = []

    normalized = state.get("normalized_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = _extract_user_input(state)

    sub_queries = state.get("sub_queries")
    if not isinstance(sub_queries, list):
        sub_queries = []
    multi_queries = state.get("multi_queries")
    if not isinstance(multi_queries, list):
        multi_queries = []
    hyde_doc = state.get("hyde_doc")
    if not isinstance(hyde_doc, str):
        hyde_doc = ""

    query_items = build_query_items(
        main_query=normalized.strip(),
        sub_queries=[q for q in sub_queries if isinstance(q, str)],
        variants=[q for q in multi_queries if isinstance(q, str)],
        hyde_doc=hyde_doc.strip() or None,
    )

    stage_summaries = _merge_stage_summary(
        state,
        "prepare_messages",
        {
            "query_items_count": len(query_items),
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    return {"query_items": query_items, "stage_summaries": stage_summaries}
