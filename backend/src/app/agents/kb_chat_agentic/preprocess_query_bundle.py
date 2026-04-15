"""KB Chat preprocess 查询准备与缓存辅助。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from langchain.messages import HumanMessage
from langgraph.runtime import Runtime

from app.agents.kb_chat_memory import resolve_kb_chat_store_user_id
from app.core.memory_store import StoreManager
from app.core.settings import Settings
from app.services.query_rewrite_service import (
    COMPLEXITY_CLASSIFY_DECISION_VERSION,
    _looks_stable_overview_query,
    build_query_items,
)

from .budget import now_iso
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


