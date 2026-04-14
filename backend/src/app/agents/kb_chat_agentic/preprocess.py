"""KB Chat agentic 预处理节点（MergeContext → HyDE）。

这些节点当前刻意保持最小实现：
- 优先采用安全的空操作或启发式行为
- 将重提示词的 LLM 行为延后到后续任务处理
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any, cast

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.kb_chat_memory import (
    aget_kb_chat_memory,
    render_kb_chat_memory_snippet,
    resolve_kb_chat_store_user_id,
)
from app.core.memory_store import StoreManager
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.services.kb_chat_context_seed import (
    build_context_seed_from_messages,
    context_seed_turns_to_context_frame_turns,
)
from app.services.query_rewrite_service import (
    COMPLEXITY_CLASSIFY_DECISION_VERSION,
    QueryRewriteService,
    _looks_stable_overview_query,
    build_query_items,
)
from app.services.query_rewrite_text import _hyde_num_hypotheses
from app.utils.token_counter import count_tokens_approximately
from app.agents.kb_chat_agentic_state import (
    AmbiguityCheckInput,
    CorefRewriteInput,
    DecompositionInput,
    GenerateVariantsInput,
    HydeInput,
    MergeContextInput,
    NormalizeRewriteInput,
    QueryPlanInput,
    QueryPlanFinalizeInput,
    merge_routing_decision,
)

from .budget import (
    ensure_budget_initialized,
    now_iso,
)
from .json_safety import ensure_json_safe
from .runtime_config import (
    parallel_retrieval_include_main,
    parallel_retrieval_max_branches,
    parallel_retrieval_min_queries,
)

_COMPLEXITY_CACHE_SCHEMA = "kb_chat_complexity_cache_v1"
_COMPLEXITY_CACHE_KEY_PREFIX = "complexity"
StateView = Mapping[str, object]


def _get_last_human(messages: list[Any]) -> HumanMessage | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


def _extract_user_input(state: StateView) -> str:
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
    normalized = sorted(
        str(k).strip() for k in kb_ids if isinstance(k, str) and str(k).strip()
    )
    if not normalized:
        return "kb_all"
    digest = hashlib.sha1(",".join(normalized).encode("utf-8")).hexdigest()[:12]
    return f"kb_{digest}"


def _complexity_cache_namespace(
    state: StateView,
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
    kb_ids_str = [
        str(k).strip() for k in kb_ids if isinstance(k, str) and str(k).strip()
    ]
    return ("kb_chat", "complexity_cache", user_id, _cache_kb_scope(kb_ids_str))


def _complexity_cache_key(
    *,
    query: str,
    recall_risk: str,
    has_multi_target: bool,
    is_comparison: bool,
    decision_version: str,
    cache_key_version: str,
) -> str:
    payload = {
        "query": query.strip(),
        "recall_risk": recall_risk.strip().lower(),
        "has_multi_target": bool(has_multi_target),
        "is_comparison": bool(is_comparison),
        "decision_version": decision_version.strip()
        or COMPLEXITY_CLASSIFY_DECISION_VERSION,
        "cache_key_version": cache_key_version.strip() or "v1",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{_COMPLEXITY_CACHE_KEY_PREFIX}:{digest}"


def _complexity_cache_store_status(
    runtime: Runtime[Any] | None,
) -> str | None:
    if runtime is None or runtime.store is None:
        return None
    try:
        status = StoreManager.status()
    except Exception:
        return None
    if not bool(status.get("degraded")):
        return None
    effective_backend = str(status.get("effective_backend") or "").strip().lower()
    if effective_backend != "memory":
        return None
    return "degraded_inmemory_store"


def _wrap_cache_with_ttl(
    payload: dict[str, Any], *, ttl_seconds: int
) -> dict[str, Any]:
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
    state: StateView,
    runtime: Runtime[Any] | None,
    cache_key: str,
) -> dict[str, Any] | None:
    if runtime is None or runtime.store is None:
        return None
    item = await runtime.store.aget(
        _complexity_cache_namespace(state, runtime), cache_key
    )
    if item is None:
        return None
    value = getattr(item, "value", None)
    if not isinstance(value, dict):
        return None
    return _unwrap_complexity_cache(value)


async def _write_complexity_cache(
    *,
    state: StateView,
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


def _resolve_prepare_strategy(state: StateView) -> str:
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
    state: StateView,
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


def resolve_prepare_budget(
    *,
    state: StateView,
    runtime: Runtime[Any],
    settings: Settings,
) -> dict[str, Any]:
    return _resolve_prepare_budget(state=state, runtime=runtime, settings=settings)


def _normalize_meta_values(
    meta: dict[str, Any] | None,
    key: str,
    *,
    limit: int,
) -> list[str]:
    if not isinstance(meta, dict):
        return []
    raw_values = meta.get(key)
    if not isinstance(raw_values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            continue
        value = raw_value.strip()
        if not value:
            continue
        lowered = value.casefold()
        if lowered in seen:
            continue
        normalized.append(value)
        seen.add(lowered)
        if len(normalized) >= limit:
            break
    return normalized


def _constraint_term_groups(meta: dict[str, Any] | None) -> dict[str, list[str]]:
    return {
        "entities": _normalize_meta_values(meta, "entities", limit=4),
        "time_constraints": _normalize_meta_values(meta, "time_constraints", limit=3),
        "metric_constraints": _normalize_meta_values(
            meta, "metric_constraints", limit=4
        ),
        "scope_constraints": _normalize_meta_values(meta, "scope_constraints", limit=4),
    }


def _constraint_terms(meta: dict[str, Any] | None) -> list[str]:
    groups = _constraint_term_groups(meta)
    return _dedupe_string_list(
        [
            *groups["entities"],
            *groups["time_constraints"],
            *groups["metric_constraints"],
            *groups["scope_constraints"],
        ]
    )


def _effective_prepare_quality_threshold(
    *,
    budget: dict[str, Any],
    normalized_meta: dict[str, Any] | None,
) -> float:
    threshold = float(budget.get("quality_threshold") or 0.52)
    if not isinstance(normalized_meta, dict):
        return max(0.0, min(threshold, 1.0))

    recall_risk = str(normalized_meta.get("recall_risk") or "").strip().lower()
    if recall_risk == "high":
        threshold -= 0.05
    elif recall_risk == "low":
        threshold += 0.02

    if bool(normalized_meta.get("drift_risk")):
        threshold += 0.04
    if normalized_meta.get("constraint_preserved") is False:
        threshold += 0.03
    return max(0.0, min(threshold, 1.0))


def score_query_item_quality(
    item: dict[str, Any],
    *,
    strategy: str,
    normalized_meta: dict[str, Any] | None = None,
) -> float:
    precomputed = item.get("quality_score")
    if isinstance(precomputed, (int, float)) and not isinstance(precomputed, bool):
        return round(max(0.0, min(float(precomputed), 1.25)), 4)

    kind = str(item.get("kind") or "other").strip() or "other"
    query = str(item.get("query") or "").strip()
    if not query:
        return 0.0

    base = {
        "main": 1.0,
        "paraphrase": 0.88,
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

    priority = item.get("priority")
    if isinstance(priority, int):
        base += max(0, 8 - max(1, min(priority, 8))) * 0.015

    if strategy == "decomposition" and kind == "subquery":
        base += 0.05
    if strategy == "paraphrase" and kind == "paraphrase":
        base += 0.04
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
        base += 0.04

    constraint_terms = _constraint_terms(normalized_meta)
    if constraint_terms:
        query_lower = query.casefold()
        matched_constraints = sum(
            1 for term in constraint_terms if term.casefold() in query_lower
        )
        base += min(matched_constraints, 4) * 0.05
        if kind in {"variant", "subquery"} and matched_constraints == 0:
            base -= 0.06

    if isinstance(normalized_meta, dict):
        recall_risk = str(normalized_meta.get("recall_risk") or "").strip().lower()
        if recall_risk == "high" and kind in {"variant", "subquery", "hyde"}:
            base += 0.04
        elif recall_risk == "low" and kind == "hyde":
            base -= 0.03

        if bool(normalized_meta.get("drift_risk")) and kind in {"variant", "hyde"}:
            base -= 0.08
        if normalized_meta.get("constraint_preserved") is False and kind != "main":
            base -= 0.12

    return round(max(0.0, min(base, 1.25)), 4)


def _prepare_quality_score(
    item: dict[str, Any],
    *,
    strategy: str,
    normalized_meta: dict[str, Any] | None = None,
) -> float:
    return score_query_item_quality(
        item,
        strategy=strategy,
        normalized_meta=normalized_meta,
    )


def _is_direct_stable_overview_query(
    *,
    original_query: str,
    normalized_query: str,
    strategy: str,
) -> bool:
    if strategy != "direct":
        return False
    for candidate in (original_query, normalized_query):
        if isinstance(candidate, str) and _looks_stable_overview_query(candidate):
            return True
    return False


def build_prepared_query_bundle(
    *,
    original_query: str,
    normalized_query: str,
    strategy: str,
    sub_queries: list[str],
    sub_query_specs: list[dict[str, Any]],
    multi_queries: list[str],
    hyde_docs: list[str],
    normalized_meta: dict[str, Any] | None,
    budget: dict[str, Any],
) -> dict[str, Any]:
    constraint_terms = _constraint_terms(normalized_meta)
    skip_hyde = _is_direct_stable_overview_query(
        original_query=original_query,
        normalized_query=normalized_query,
        strategy=strategy,
    )

    variant_candidates: list[str] = []
    variant_source_by_query: dict[str, str] = {}

    def _add_variant_candidate(query: str, source: str) -> None:
        value = str(query or "").strip()
        if not value:
            return
        lowered = value.casefold()
        if lowered in variant_source_by_query:
            return
        variant_source_by_query[lowered] = source
        variant_candidates.append(value)

    for query in multi_queries:
        _add_variant_candidate(query, "multi_query")

    raw_items = build_query_items(
        main_query=normalized_query or original_query,
        sub_queries=sub_queries,
        sub_query_specs=sub_query_specs,
        variants=_dedupe_string_list(variant_candidates),
        hyde_docs=None if skip_hyde else (hyde_docs or None),
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
            source = variant_source_by_query.get(query.casefold(), "multi_query")
        elif kind == "hyde":
            source = "hyde"

        scored_rows.append(
            {
                "index": idx,
                "kind": kind,
                "query": query,
                "source": source,
                "priority": max(1, min(int(priority), 8)),
                "quality_score": _prepare_quality_score(
                    item,
                    strategy=strategy,
                    normalized_meta=normalized_meta,
                ),
                "item": item,
            }
        )

    deduped_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    if skip_hyde and hyde_docs:
        hyde_query = str(hyde_docs[0] or "").strip()
        dropped_rows.append(
            {
                "kind": "hyde",
                "query": hyde_query,
                "reason": "stable_overview_direct_disable_hyde",
            }
        )
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

    quality_threshold = _effective_prepare_quality_threshold(
        budget=budget,
        normalized_meta=normalized_meta,
    )
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
            (row for row in filtered_rows if str(row.get("kind") or "") == "main"),
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
        if not item:
            continue
        selected_items.append(
            {
                **item,
                "priority": int(row.get("priority") or item.get("priority") or 1),
                "quality_score": float(row.get("quality_score") or 0.0),
            }
        )

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
    if skip_hyde and hyde_docs:
        quality_signals.append("stable_overview_direct_skip_hyde")
    if constraint_terms:
        quality_signals.append("constraint_terms_used")
    if isinstance(normalized_meta, dict):
        recall_risk = str(normalized_meta.get("recall_risk") or "").strip().lower()
        if recall_risk:
            quality_signals.append(f"recall_risk:{recall_risk}")
        if bool(normalized_meta.get("drift_risk")):
            quality_signals.append("drift_risk")
        if normalized_meta.get("constraint_preserved") is False:
            quality_signals.append("constraint_preservation_uncertain")
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
            "quality_threshold": quality_threshold,
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

    return {
        "query_items": selected_items,
        "message_plan": message_plan,
        "query_bundle": query_bundle,
        "prepare_diagnostics": {
            "quality_signals": quality_signals,
            "fallback_reason": fallback_reason,
        },
    }


def _merge_stage_summary(
    state: StateView, key: str, summary: dict[str, Any], *, settings: Settings
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
    """没有显式摘要时使用的对话上下文兜底。"""
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
    seed = build_context_seed_from_messages(
        summary_text="",
        messages=messages,
        question="",
        max_turns=max_turns,
    )
    return context_seed_turns_to_context_frame_turns(seed["recent_turns"])


def _dedupe_turns_preserve_latest(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    if not turns:
        return []
    deduped_reversed: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for turn in reversed(turns):
        role = str(turn.get("role") or "assistant").strip() or "assistant"
        text = str(turn.get("text") or "").strip()
        normalized_text = _normalize_for_compare(text)
        if not normalized_text:
            continue
        key = (role, normalized_text)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append({"role": role, "text": text})
    deduped_reversed.reverse()
    return deduped_reversed


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
                if (
                    role == "用户"
                    and _normalize_for_compare(text) == normalized_question
                ):
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
        from langmem.short_term.summarization import TokenCounter
    except Exception:  # pragma: no cover
        return ""

    try:
        model = create_chat_model(settings=settings)
        summary_model = model.bind(max_tokens=settings.summary_max_tokens)
        token_counter_fn: TokenCounter
        candidate_counter = getattr(model, "get_num_tokens_from_messages", None)
        if callable(candidate_counter):
            token_counter_fn = cast(TokenCounter, candidate_counter)
        else:
            def _fallback_token_counter(msgs: Iterable[Any]) -> int:
                return sum(
                    count_tokens_approximately(getattr(m, "content", "") or "")
                    for m in msgs
                )
            token_counter_fn = _fallback_token_counter
    except Exception:  # pragma: no cover
        return ""

    def _run() -> object:
        return summarize_messages(
            lc_messages,
            running_summary=None,
            token_counter=token_counter_fn,
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
    return _dedupe_turns_preserve_latest(selected[-max_turns * 2 :])


def _filter_memory_entries_already_covered_by_turns(
    memory: dict[str, Any] | None,
    *,
    question: str,
    turns: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not isinstance(memory, dict):
        return None
    raw_entries = memory.get("entries")
    if not isinstance(raw_entries, list):
        return memory

    normalized_question = _normalize_for_compare(question)
    user_texts = {normalized_question} if normalized_question else set()
    assistant_texts: set[str] = set()
    for turn in turns:
        role = str(turn.get("role") or "assistant").strip().lower()
        normalized_text = _normalize_for_compare(str(turn.get("text") or ""))
        if not normalized_text:
            continue
        if role == "user":
            user_texts.add(normalized_text)
        elif role == "assistant":
            assistant_texts.add(normalized_text)

    filtered_entries: list[Any] = []
    for entry in raw_entries:
        record = _as_dict(entry)
        if not record:
            filtered_entries.append(entry)
            continue
        q = _normalize_for_compare(str(record.get("q") or ""))
        a = _normalize_for_compare(str(record.get("a") or ""))
        if q and a and q in user_texts and a in assistant_texts:
            continue
        filtered_entries.append(record)

    filtered_memory = dict(memory)
    filtered_memory["entries"] = filtered_entries
    return filtered_memory


def _needs_conflict_resolution(*, summary_text: str, memory_snippet: str) -> bool:
    if not summary_text or not memory_snippet:
        return False
    summary_numbers = set(re.findall(r"\d+", summary_text))
    memory_numbers = set(re.findall(r"\d+", memory_snippet))
    return bool(
        summary_numbers
        and memory_numbers
        and summary_numbers.isdisjoint(memory_numbers)
    )


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

    memory_data: dict[str, Any] | None = None
    memory_snippet = ""
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
            )
            if isinstance(mem, dict):
                memory_data = mem
                memory_snippet = render_kb_chat_memory_snippet(mem)
        except Exception:  # pragma: no cover
            memory_data = None
            memory_snippet = ""

    question = user_input.strip()
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


def _default_decomposition_plan(query: str = "") -> dict[str, Any]:
    normalized = query.strip()
    return {
        "strategy": "direct",
        "version": "kb_chat_decomposition_plan_v2",
        "sub_query_specs": [
            {
                "query": normalized,
                "priority": 1,
                "coverage_tags": [],
                "purpose": "canonical",
            }
        ]
        if normalized
        else [],
        "risk_flags": [],
        "reasoning": "",
    }


def _resolve_query_plan_next_node(*, strategy: str, settings: Settings) -> str:
    if strategy == "decomposition":
        if bool(getattr(settings, "kb_chat_decomposition_enabled", True)):
            return "decomposition"
        if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
            return "generate_variants"
        return "hyde"
    if strategy == "multi_query":
        if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
            return "generate_variants"
        return "hyde"
    return "hyde"


def _complexity_level_for_strategy(strategy: str) -> str:
    if strategy == "decomposition":
        return "complex"
    if strategy == "multi_query":
        return "moderate"
    return "simple"


async def _classify_query_strategy(
    *,
    state: StateView,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    query = _resolve_query_plan_original_query(state)
    if not query:
        normalized_query = state.get("normalized_query")
        if isinstance(normalized_query, str) and normalized_query.strip():
            query = normalized_query.strip()
    if not query:
        query = _extract_user_input(state)

    strategy = "direct"
    success = False
    reasoning: str | None = None
    failure_reason: str | None = None
    confidence = 0.0
    risk_flags: list[str] = []
    decision_version = COMPLEXITY_CLASSIFY_DECISION_VERSION
    cache_hit = False
    cache_status = "disabled"
    cache_key_version = "v2"
    normalized_meta = state.get("normalized_meta")
    if not isinstance(normalized_meta, dict):
        normalized_meta = {}
    recall_risk = str(normalized_meta.get("recall_risk") or "unknown")
    has_multi_target = bool(normalized_meta.get("has_multi_target"))
    is_comparison = bool(normalized_meta.get("is_comparison"))
    cache_enabled = bool(getattr(settings, "kb_chat_complexity_cache_enabled", True))
    degraded_cache_status = _complexity_cache_store_status(runtime)
    cache_key = _complexity_cache_key(
        query=query,
        recall_risk=recall_risk,
        has_multi_target=has_multi_target,
        is_comparison=is_comparison,
        decision_version=decision_version,
        cache_key_version=cache_key_version,
    )
    if cache_enabled:
        if runtime is None or runtime.store is None:
            cache_status = "no_store"
        else:
            if degraded_cache_status is not None:
                cache_status = degraded_cache_status
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
                candidate_strategy = (
                    str(cached.get("strategy") or "direct").strip().lower()
                )
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
                failure_reason = None
                decision_version = (
                    str(
                        cached.get("decision_version")
                        or COMPLEXITY_CLASSIFY_DECISION_VERSION
                    ).strip()
                    or COMPLEXITY_CLASSIFY_DECISION_VERSION
                )
                cached_risk_flags = cached.get("risk_flags")
                raw_flags = (
                    cached_risk_flags if isinstance(cached_risk_flags, list) else []
                )
                risk_flags = [
                    str(flag).strip()
                    for flag in raw_flags
                    if isinstance(flag, str) and flag.strip()
                ][:8]
                cache_hit = True
                if degraded_cache_status is None:
                    cache_status = "hit"
            elif cache_status not in {"read_error", "degraded_inmemory_store"}:
                cache_status = "miss"

    if not cache_hit:
        try:
            svc = QueryRewriteService(settings=settings)
            decision = await svc.classify_complexity(
                query,
                recall_risk=recall_risk,
                has_multi_target=has_multi_target,
                is_comparison=is_comparison,
            )
            strategy = (
                decision.strategy
                if decision.strategy in {"direct", "decomposition", "multi_query"}
                else "direct"
            )
            success = decision.success
            reasoning = decision.reasoning
            failure_reason = getattr(decision, "failure_reason", None)
            confidence = round(max(0.0, min(1.0, float(decision.confidence or 0.0))), 4)
            decision_version = str(
                decision.decision_version or COMPLEXITY_CLASSIFY_DECISION_VERSION
            ).strip()
            if not decision_version:
                decision_version = COMPLEXITY_CLASSIFY_DECISION_VERSION
            raw_flags = (
                decision.risk_flags if isinstance(decision.risk_flags, list) else []
            )
            risk_flags = [
                str(flag).strip()
                for flag in raw_flags
                if isinstance(flag, str) and flag.strip()
            ][:8]
        except Exception:  # pragma: no cover
            strategy = "direct"
            success = False
            reasoning = None
            failure_reason = "error"
        if cache_enabled and success:
            try:
                await _write_complexity_cache(
                    state=state,
                    runtime=runtime,
                    cache_key=cache_key,
                    ttl_seconds=max(
                        0,
                        int(
                            getattr(
                                settings, "kb_chat_complexity_cache_ttl_seconds", 120
                            )
                        ),
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

    return {
        "strategy": strategy,
        "success": success,
        "reasoning": reasoning,
        "failure_reason": failure_reason,
        "confidence": confidence,
        "risk_flags": risk_flags,
        "decision_version": decision_version,
        "recall_risk": recall_risk,
        "has_multi_target": has_multi_target,
        "is_comparison": is_comparison,
        "cache_hit": cache_hit,
        "cache_status": cache_status,
        "cache_key_version": cache_key_version,
    }


async def query_plan(
    state: QueryPlanInput,
    runtime: Runtime[Any],
    settings: Settings,
) -> Command[str]:
    """对问题复杂度分类，并路由到实时 Scheme B 增强链路。"""

    start = time.perf_counter()
    decision = await _classify_query_strategy(
        state=state,
        settings=settings,
        runtime=runtime,
    )
    strategy = str(decision.get("strategy") or "direct")
    next_node = _resolve_query_plan_next_node(strategy=strategy, settings=settings)
    stage_summaries = _merge_stage_summary(
        state,
        "query_plan",
        {
            "strategy": strategy,
            "confidence": float(decision.get("confidence") or 0.0),
            "risk_flags": decision.get("risk_flags") or [],
            "decision_version": decision.get("decision_version"),
            "recall_risk": decision.get("recall_risk"),
            "has_multi_target": decision.get("has_multi_target"),
            "is_comparison": decision.get("is_comparison"),
            "reasoning": decision.get("reasoning"),
            "failure_reason": decision.get("failure_reason"),
            "success": bool(decision.get("success")),
            "next_node": next_node,
            "cache_hit": bool(decision.get("cache_hit")),
            "complexity_cache_status": decision.get("cache_status"),
            "cache_key_version": decision.get("cache_key_version"),
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )
    normalized = state.get("normalized_query")
    normalized_query = normalized.strip() if isinstance(normalized, str) else ""
    updates: dict[str, Any] = {
        "query_strategy": strategy,
        "complexity_level": _complexity_level_for_strategy(strategy),
        "query_strategy_confidence": float(decision.get("confidence") or 0.0),
        "query_strategy_signals": decision.get("risk_flags") or [],
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": [],
        "decomposition_plan": _default_decomposition_plan(normalized_query),
        "query_items": [],
        "query_plan_result": {},
        "query_plan_diagnostics": {},
        "stage_summaries": stage_summaries,
    }
    return Command(update=updates, goto=next_node)


async def decomposition(state: DecompositionInput, settings: Settings) -> Command[str]:
    """生成子查询（经 QueryRewriteService，安全降级）。"""
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

    stage_summaries["decomposition"]["next_node"] = "hyde"
    return Command(
        update={
            "sub_queries": sub_queries,
            "decomposition_plan": decomposition_plan,
            "stage_summaries": stage_summaries,
        },
        goto="hyde",
    )


async def generate_variants(
    state: GenerateVariantsInput,
    settings: Settings,
) -> Command[str]:
    """生成查询变体（经 QueryRewriteService，安全降级）。"""
    start = time.perf_counter()
    query = _resolve_query_plan_original_query(state)
    if not query:
        normalized_query = state.get("normalized_query")
        if isinstance(normalized_query, str) and normalized_query.strip():
            query = normalized_query.strip()
    if not query:
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
            "alias_count": 0,
            "success": success,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    stage_summaries["generate_variants"]["next_node"] = "hyde"
    return Command(
        update={"multi_queries": deduped, "stage_summaries": stage_summaries},
        goto="hyde",
    )


async def hyde(state: HydeInput, settings: Settings) -> dict[str, Any]:
    """HyDE 节点（LLM 驱动，带安全兜底）。"""
    start = time.perf_counter()
    query = _resolve_query_plan_normalized_query(state)
    original_query = _resolve_query_plan_original_query(state) or query
    strategy = _resolve_prepare_strategy(state)
    if _is_direct_stable_overview_query(
        original_query=original_query,
        normalized_query=query,
        strategy=strategy,
    ):
        stage_summaries = _merge_stage_summary(
            state,
            "hyde",
            {
                "driver": "rule",
                "success": True,
                "requested_count": 0,
                "generated_count": 0,
                "retry_regenerated": False,
                "reason": "stable_overview_direct_skip_hyde",
                "completed_at": now_iso(),
                "latency_ms": int((time.perf_counter() - start) * 1000),
            },
            settings=settings,
        )
        return {"hyde_docs": [], "stage_summaries": stage_summaries}
    hyde_docs: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.hyde(query)
        hyde_docs = [
            item for item in result.queries if isinstance(item, str) and item.strip()
        ]
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        hyde_docs = []
        success = False
        reason = "error"
    loop_counts = state.get("loop_counts")
    retry_regenerated = (
        isinstance(loop_counts, dict)
        and int(loop_counts.get("retrieval_retries") or 0) > 0
    )

    stage_summaries = _merge_stage_summary(
        state,
        "hyde",
        {
            "driver": "llm",
            "success": success,
            "requested_count": _hyde_num_hypotheses(),
            "generated_count": len(hyde_docs),
            "retry_regenerated": retry_regenerated,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"hyde_docs": hyde_docs, "stage_summaries": stage_summaries}


def _resolve_query_plan_original_query(state: StateView) -> str:
    original_query = state.get("resolved_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = state.get("coref_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = state.get("rewrite_input_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = _extract_user_input(state)
    return original_query.strip()


def _resolve_query_plan_normalized_query(state: StateView) -> str:
    normalized = state.get("normalized_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = state.get("resolved_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = state.get("coref_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = _extract_user_input(state)
    return normalized.strip()


def _build_query_plan_fallback_policy(
    *,
    strategy: str,
    normalized_meta: dict[str, Any],
    settings: Settings,
    stable_overview: bool = False,
) -> dict[str, bool]:
    recall_risk = str(normalized_meta.get("recall_risk") or "medium").strip().lower()
    allow_broaden = strategy in {"decomposition", "multi_query"} or recall_risk in {
        "medium",
        "high",
    }
    return {
        "allow_broaden": allow_broaden,
        "allow_hyde": not (strategy == "direct" and stable_overview),
        "allow_retry_rewrite": True,
    }


def _build_query_plan_finalize_update(
    *,
    state: StateView,
    runtime: Runtime[Any],
    settings: Settings,
    latency_ms: int,
) -> dict[str, Any]:
    normalized = _resolve_query_plan_normalized_query(state)
    original_query = _resolve_query_plan_original_query(state) or normalized
    stable_overview = _is_direct_stable_overview_query(
        original_query=original_query,
        normalized_query=normalized,
        strategy=_resolve_prepare_strategy(state),
    )
    normalized_meta = _as_dict(state.get("normalized_meta")) or {}
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

    hyde_docs_raw = state.get("hyde_docs")
    if not isinstance(hyde_docs_raw, list):
        hyde_docs_raw = []
    hyde_docs = [doc for doc in hyde_docs_raw if isinstance(doc, str) and doc.strip()]

    strategy = _resolve_prepare_strategy(state)
    budget = resolve_prepare_budget(state=state, runtime=runtime, settings=settings)
    bundle = build_prepared_query_bundle(
        original_query=original_query,
        normalized_query=normalized,
        strategy=strategy,
        sub_queries=sub_queries,
        sub_query_specs=sub_query_specs,
        multi_queries=multi_queries,
        hyde_docs=hyde_docs,
        normalized_meta=normalized_meta,
        budget=budget,
    )
    prepare_diagnostics = {
        **(_as_dict(bundle.get("prepare_diagnostics")) or {}),
        "timing": {"latency_ms": latency_ms},
    }
    message_plan = _as_dict(bundle.get("message_plan")) or {}
    query_bundle = _as_dict(bundle.get("query_bundle")) or {}
    raw_query_items = bundle.get("query_items")
    query_items: list[Any] = raw_query_items if isinstance(raw_query_items, list) else []
    fallback_reason = str(prepare_diagnostics.get("fallback_reason") or "").strip()
    if fallback_reason.lower() == "none":
        fallback_reason = ""
    dedup_stats = _as_dict(query_bundle.get("dedup_stats")) or {}
    stage_summaries_state = _as_dict(state.get("stage_summaries")) or {}
    query_plan_summary = _as_dict(stage_summaries_state.get("query_plan")) or {}
    raw_candidates = message_plan.get("candidates")
    candidates: list[Any] = raw_candidates if isinstance(raw_candidates, list) else []
    quality_signals = (
        prepare_diagnostics.get("quality_signals")
        if isinstance(prepare_diagnostics.get("quality_signals"), list)
        else []
    )
    kind_breakdown = _as_dict(query_bundle.get("kind_breakdown")) or {}
    rejection_counts = {
        "fragment_rejected": 0,
        "duplicate_rejected": int(dedup_stats.get("duplicate_dropped") or 0),
        "low_quality_rejected": int(dedup_stats.get("low_quality_dropped") or 0),
        "over_budget_rejected": sum(
            1
            for item in message_plan.get("dropped") or []
            if isinstance(item, dict) and str(item.get("reason") or "") == "over_budget"
        ),
    }
    query_plan_result = ensure_json_safe(
        {
            "strategy": strategy,
            "reasoning": str(query_plan_summary.get("reasoning") or ""),
            "fallback_policy": _build_query_plan_fallback_policy(
                strategy=strategy,
                normalized_meta=normalized_meta,
                settings=settings,
                stable_overview=stable_overview,
            ),
        },
        settings=settings,
        label="query_plan_result",
    )
    query_plan_diagnostics_payload = ensure_json_safe(
        {
            "candidate_count": len(candidates),
            "selected_count": len(query_items),
            "fallback_reason": fallback_reason,
            "latency_ms": latency_ms,
            "rejection_counts": rejection_counts,
            "quality_signals": quality_signals,
            "kind_breakdown": kind_breakdown,
            "budget": _as_dict(message_plan.get("budget")) or budget,
        },
        settings=settings,
        label="query_plan_diagnostics",
    )
    query_plan_diagnostics = _as_dict(query_plan_diagnostics_payload) or {}
    safe_query_items = ensure_json_safe(
        query_items, settings=settings, label="query_items"
    )
    stage_summaries = _merge_stage_summary(
        state,
        "query_plan_finalize",
        {
            "strategy": strategy,
            "query_count": len(query_items),
            "candidate_count": len(candidates),
            "selected_count": len(query_items),
            "rejection_counts": query_plan_diagnostics.get("rejection_counts") or {},
            "fallback_reason": fallback_reason or None,
            "kind_breakdown": kind_breakdown,
            "latency_ms": latency_ms,
            "completed_at": now_iso(),
        },
        settings=settings,
    )
    return {
        "query_strategy": strategy,
        "query_plan_result": query_plan_result,
        "query_plan_diagnostics": query_plan_diagnostics_payload,
        "query_items": safe_query_items,
        "stage_summaries": stage_summaries,
    }


async def query_plan_finalize(
    state: QueryPlanFinalizeInput,
    runtime: Runtime[Any],
    settings: Settings,
) -> Command[str]:
    """将 Scheme B 查询规划定稿为可直接检索的 query_items。"""

    start = time.perf_counter()
    update = _build_query_plan_finalize_update(
        state=state,
        runtime=runtime,
        settings=settings,
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    fallback_reason = str(
        update["query_plan_diagnostics"].get("fallback_reason") or "none"
    )
    outer_next_node = "retrieval_subgraph"
    action = "none"
    reason = "query_planned"
    reason_code = "query_planned"
    if fallback_reason != "none":
        outer_next_node = "transform_query"
        action = "transform_query"
        reason = fallback_reason
        reason_code = fallback_reason
        reflection = _as_dict(state.get("reflection")) or {}
        update["reflection"] = {
            **reflection,
            "action": "transform_query",
            "reason": fallback_reason,
        }
    update = {
        **update,
        **merge_routing_decision(
            state,
            "preprocess",
            {
                "phase": "preprocess",
                "next_node": outer_next_node,
                "action": action,
                "reason": reason,
                "reason_code": reason_code,
                "decision_source": "query_plan_finalize",
                "completed_at": now_iso(),
            },
            updates=update,
        ),
    }
    return Command(update=update, goto="preprocess_exit")


def _merge_query_plan_state(
    base: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    merged = {**base, **patch}
    for key in ("stage_summaries", "routing_decisions", "reflection"):
        base_value = base.get(key)
        patch_value = patch.get(key)
        if isinstance(base_value, dict) and isinstance(patch_value, dict):
            merged[key] = {**base_value, **patch_value}
    return merged


def _command_update_payload(result: Command[str] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, Command):
        return result.update if isinstance(result.update, dict) else {}
    return result if isinstance(result, dict) else {}


def _command_goto(result: Command[str] | dict[str, Any]) -> str | None:
    if isinstance(result, Command):
        goto = result.goto
        return goto if isinstance(goto, str) and goto.strip() else None
    return None


async def run_query_plan_scheme_b(
    state: dict[str, Any],
    *,
    runtime: Runtime[Any] | None,
    settings: Settings,
) -> dict[str, Any]:
    """用与预处理阶段一致的实时 Scheme B 语义重建查询规划。"""

    effective_runtime = runtime
    if effective_runtime is None:
        effective_runtime = SimpleNamespace(context={}, store=None)

    current_state = dict(state)
    accumulated_updates: dict[str, Any] = {}
    effective_runtime_typed = cast(Runtime[Any], effective_runtime)

    decision = await query_plan(
        cast(QueryPlanInput, current_state),
        runtime=effective_runtime_typed,
        settings=settings,
    )
    decision_updates = _command_update_payload(decision)
    accumulated_updates = _merge_query_plan_state(accumulated_updates, decision_updates)
    current_state = _merge_query_plan_state(current_state, decision_updates)
    next_node = _command_goto(decision) or "query_plan_finalize"

    while next_node in {"decomposition", "generate_variants", "hyde"}:
        if next_node == "decomposition":
            step_result = await decomposition(
                cast(DecompositionInput, current_state), settings=settings
            )
        elif next_node == "generate_variants":
            step_result = await generate_variants(
                cast(GenerateVariantsInput, current_state), settings=settings
            )
        else:
            step_result = await hyde(cast(HydeInput, current_state), settings=settings)

        step_updates = _command_update_payload(step_result)
        accumulated_updates = _merge_query_plan_state(accumulated_updates, step_updates)
        current_state = _merge_query_plan_state(current_state, step_updates)
        next_node = _command_goto(step_result) or "query_plan_finalize"

    finalize_latency_ms = 0
    finalize_updates = _build_query_plan_finalize_update(
        state=current_state,
        runtime=effective_runtime_typed,
        settings=settings,
        latency_ms=finalize_latency_ms,
    )
    accumulated_updates = _merge_query_plan_state(accumulated_updates, finalize_updates)
    return accumulated_updates
