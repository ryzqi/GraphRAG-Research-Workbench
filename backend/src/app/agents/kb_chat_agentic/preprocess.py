"""KB Chat agentic preprocess nodes (MergeContext → HyDE).

These nodes are intentionally minimal first:
- Prefer safe no-op / heuristic behaviors
- Defer prompt-heavy LLM behaviors to later tasks (see OpenSpec tasks 1.4/1.11)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.agents.kb_chat_memory import (
    aget_kb_chat_memory,
    render_kb_chat_memory_snippet,
)
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.services.query_rewrite_service import (
    HYDE_NUM_HYPOTHESES,
    QueryRewriteService,
    build_query_items,
)
from app.utils.token_counter import count_tokens_approximately

from .budget import (
    ensure_budget_initialized,
    now_iso,
)
from .json_safety import ensure_json_safe
from .runtime_config import (
    ambiguity_check_enabled,
    hyde_enabled,
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
    display_context = _render_display_context(
        summary=f"对话摘要：\n{summary_text}" if summary_text else "",
        turns=selected_turns,
        memory_snippet=memory_for_render,
        question=question,
    )
    merged = display_context or question
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
        "display_context": merged,
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
        coref_meta = state.get("coref_meta")
        if isinstance(coref_meta, dict) and bool(coref_meta.get("needs_clarification")):
            ambiguous = True
            reverse_question = str(
                coref_meta.get("clarification_hint")
                or "为了更准确地回答，你指的是哪个对象/范围？请补充具体指代或上下文。"
            )
            reason = "coref_low_confidence"
        else:
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
    input_source = "coref_query"
    query = state.get("coref_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)
        input_source = "user_input"

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
    return {"normalized_query": rewritten, "stage_summaries": stage_summaries}


def route_after_complexity_router(state: dict, settings: Settings) -> str:
    """Route by complexity router result."""
    del settings
    strategy = state.get("query_strategy")
    if strategy == "decomposition":
        return "decomposition"
    if strategy == "multi_query":
        return "multi_query"
    return "direct"


async def complexity_router(state: dict, settings: Settings) -> dict[str, Any]:
    """Decide preprocess strategy: direct / decomposition / multi-query."""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    strategy = "direct"
    success = False
    reasoning: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        decision = await svc.classify_complexity(query)
        strategy = (
            decision.strategy
            if decision.strategy in {"direct", "decomposition", "multi_query"}
            else "direct"
        )
        success = decision.success
        reasoning = decision.reasoning
    except Exception:  # pragma: no cover
        strategy = "direct"
        success = False

    stage_summaries = _merge_stage_summary(
        state,
        "complexity_router",
        {
            "strategy": strategy,
            "reasoning": reasoning,
            "success": success,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    # Reset fan-out artifacts before entering the selected branch.
    return {
        "query_strategy": strategy,
        "sub_queries": [],
        "multi_queries": [],
        "stage_summaries": stage_summaries,
    }


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
        result = await svc.decompose(query)
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
        result = await svc.generate_variants(query)
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
    hyde_docs: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        enabled = hyde_enabled(state, settings)
        result = await svc.hyde(query, enabled=enabled)
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
            "enabled": hyde_enabled(state, settings),
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


async def prepare_messages(state: dict, settings: Settings) -> dict[str, Any]:
    """Build query_items for downstream retrieval/reflection layers.

    Note: We intentionally do NOT inject extra SystemMessage hints into `messages` to avoid
    leaking internal artifacts to clients via message streaming.
    """
    start = time.perf_counter()
    normalized = state.get("normalized_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = _extract_user_input(state)

    sub_queries = state.get("sub_queries")
    if not isinstance(sub_queries, list):
        sub_queries = []
    multi_queries = state.get("multi_queries")
    if not isinstance(multi_queries, list):
        multi_queries = []
    hyde_docs = state.get("hyde_docs")
    if not isinstance(hyde_docs, list):
        hyde_docs = []
    normalized_hyde_docs = [doc for doc in hyde_docs if isinstance(doc, str) and doc.strip()]

    query_items = build_query_items(
        main_query=normalized.strip(),
        sub_queries=[q for q in sub_queries if isinstance(q, str)],
        variants=[q for q in multi_queries if isinstance(q, str)],
        hyde_docs=normalized_hyde_docs or None,
    )

    stage_summaries = _merge_stage_summary(
        state,
        "prepare_messages",
        {
            "query_items_count": len(query_items),
            "hyde_docs_count": len(normalized_hyde_docs),
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    return {"query_items": query_items, "stage_summaries": stage_summaries}
