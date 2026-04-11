from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas.query_enhancement import QueryItem
from app.services.query_rewrite_contracts import (
    DECOMPOSITION_MAX_SUB_QUERIES,
    HYDE_AGGREGATION,
    HYDE_NUM_HYPOTHESES,
    MULTI_QUERY_FIXED_VARIANTS,
)
from app.services.query_rewrite_text import (
    _LEADING_COMPARE_PATTERNS,
    _MULTI_QUERY_LABEL_TOKENS,
    _TRAILING_COMPARE_PATTERNS,
    _TROUBLESHOOT_KEYWORDS,
    _dedupe_keep_order,
    _is_taxonomy_intent_drift_variant,
    _looks_compare_or_multi_target,
    _looks_taxonomy_query,
    _normalize_whitespace,
    _strip_list_prefix,
    _taxonomy_focus,
)
def _rule_based_multi_query_candidates(query: str) -> list[str]:
    q = _normalize_whitespace(query)
    if not q:
        return []

    def _default_focus(text: str) -> str:
        focus = re.sub(r"^(?:请)?(?:介绍|解释|说明|分析|总结|聊聊|请问)\s*", "", text)
        focus = re.sub(r"(?:是什么|是啥|有哪些|如何|怎么做|怎么办)\s*$", "", focus)
        return _normalize_whitespace(focus) or text

    def _comparison_focus(text: str) -> str:
        focus = text
        for pattern in _LEADING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        for pattern in _TRAILING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        focus = re.sub(r"\b(?:vs|versus)\b", " ", focus, flags=re.IGNORECASE)
        focus = re.sub(r"[，,、/]+", " ", focus)
        focus = focus.replace(" 和 ", " ").replace(" 与 ", " ").replace(" 及 ", " ")
        focus = focus.replace("和", " ").replace("与", " ").replace("及", " ")
        focus = focus.replace("的", " ")
        return _normalize_whitespace(focus) or text

    lowered = q.lower()
    if _looks_taxonomy_query(q):
        focus = _taxonomy_focus(q) or _default_focus(q)
        return [
            q,
            f"{focus} 主要变体 类型 分类",
            f"{focus} 常见变体 列表",
        ]
    if _looks_compare_or_multi_target(q):
        focus = _comparison_focus(q)
        return [
            q,
            f"{focus} 原理 机制 对比",
            f"{focus} 适用场景 优缺点",
        ]
    if any(keyword in lowered for keyword in _TROUBLESHOOT_KEYWORDS):
        focus = _default_focus(q)
        return [
            q,
            f"{focus} 原因 排查",
            f"{focus} 解决方案 最佳实践",
        ]
    focus = _default_focus(q)
    return [
        q,
        f"{focus} 核心概念 定义",
        f"{focus} 应用场景 限制",
    ]


def _rule_based_decomposition_candidates(query: str) -> list[dict[str, object]]:
    q = _normalize_whitespace(query)
    if not q:
        return []

    def _clean_clause(text: str) -> str:
        clause = _normalize_whitespace(text)
        clause = clause.strip("，。；;,.!?？! ")
        clause = re.sub(r"^(?:请)?(?:帮我)?", "", clause)
        clause = re.sub(r"(?:是什么|是啥|有哪些|如何|怎么办|怎么做)\s*$", "", clause)
        return _normalize_whitespace(clause)

    def _comparison_focus(text: str) -> str:
        focus = text
        for pattern in _LEADING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        for pattern in _TRAILING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        focus = re.sub(r"\b(?:vs|versus)\b", " ", focus, flags=re.IGNORECASE)
        focus = re.sub(r"[，,、/]+", " ", focus)
        return _normalize_whitespace(focus)

    candidates: list[dict[str, object]] = []
    seen: set[str] = set()

    def _append(text: str, *, purpose: str, tags: list[str]) -> None:
        normalized = _clean_clause(text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(
            {
                "query": normalized,
                "purpose": purpose,
                "coverage_tags": tags,
            }
        )

    clause_split = re.split(
        r"(?:，|,)?(?:并说明|并概括|并总结|并分析|并阐述|并补充|同时说明|同时概括|以及说明|以及分析)",
        q,
        maxsplit=1,
    )
    primary_clause = clause_split[0] if clause_split else q
    secondary_clause = clause_split[1] if len(clause_split) > 1 else ""

    primary_focus = (
        _comparison_focus(primary_clause)
        if _looks_compare_or_multi_target(primary_clause)
        else primary_clause
    )
    _append(primary_focus, purpose="primary_compare", tags=["comparison"])
    if secondary_clause:
        _append(secondary_clause, purpose="secondary_clause", tags=["follow_up"])

    if len(candidates) < 2 and _looks_compare_or_multi_target(q):
        comparison_query = primary_focus or q
        _append(
            f"{comparison_query} 核心区别 对比",
            purpose="comparison_summary",
            tags=["comparison"],
        )
        _append(
            f"{comparison_query} 分别 作用 角色",
            purpose="role_split",
            tags=["multi_target"],
        )

    if len(candidates) < 2:
        fallback_focus = _clean_clause(q)
        _append(
            f"{fallback_focus} 子问题 1", purpose="fallback_part_1", tags=["fallback"]
        )
        _append(
            f"{fallback_focus} 子问题 2", purpose="fallback_part_2", tags=["fallback"]
        )

    normalized_specs: list[dict[str, object]] = []
    for idx, item in enumerate(candidates[:DECOMPOSITION_MAX_SUB_QUERIES], start=1):
        normalized_specs.append(
            {
                "query": item["query"],
                "priority": idx,
                "coverage_tags": item["coverage_tags"],
                "purpose": item["purpose"],
            }
        )
    return normalized_specs


def _is_label_stuffed_multi_query(candidate: str, *, original_query: str) -> bool:
    normalized_candidate = _normalize_whitespace(candidate)
    normalized_original = _normalize_whitespace(original_query)
    if not normalized_candidate or not normalized_original:
        return False
    if normalized_candidate == normalized_original:
        return False
    if not normalized_candidate.startswith(normalized_original):
        return False
    suffix = _normalize_whitespace(normalized_candidate[len(normalized_original) :])
    if not suffix:
        return False
    tokens = [token.strip() for token in re.split(r"\s+", suffix) if token.strip()]
    if not tokens:
        return False
    return all(token in _MULTI_QUERY_LABEL_TOKENS for token in tokens)


def _normalize_multi_query_variants(
    queries: Iterable[str], *, original_query: str
) -> tuple[list[str], str | None]:
    normalized: list[str] = []
    invalid_reason: str | None = None
    original = _normalize_whitespace(original_query)
    for candidate in _dedupe_keep_order(queries):
        if _is_label_stuffed_multi_query(candidate, original_query=original):
            invalid_reason = invalid_reason or "label_stuffing"
            continue
        if _is_taxonomy_intent_drift_variant(candidate, original_query=original_query):
            continue
        normalized.append(candidate)
    distinct_from_original = [
        candidate
        for candidate in normalized
        if _normalize_whitespace(candidate) != original
    ]
    if len(distinct_from_original) < 2:
        invalid_reason = invalid_reason or "insufficient_distinct_queries"
    return normalized, invalid_reason


def _coerce_fixed_multi_query_variants(
    queries: Iterable[str], *, original_query: str
) -> tuple[list[str], bool, str | None]:
    base, invalid_reason = _normalize_multi_query_variants(
        queries,
        original_query=original_query,
    )
    if len(base) >= MULTI_QUERY_FIXED_VARIANTS:
        return base[:MULTI_QUERY_FIXED_VARIANTS], False, invalid_reason

    completed = _dedupe_keep_order(
        [*base, *_rule_based_multi_query_candidates(original_query)]
    )
    if len(completed) < MULTI_QUERY_FIXED_VARIANTS:
        for idx in range(len(completed), MULTI_QUERY_FIXED_VARIANTS):
            completed.append(f"{_normalize_whitespace(original_query)} 变体{idx + 1}")
    return completed[:MULTI_QUERY_FIXED_VARIANTS], True, invalid_reason


def _normalize_hyde_documents(
    docs: Iterable[str], *, limit: int = HYDE_NUM_HYPOTHESES
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        value = _normalize_whitespace(_strip_list_prefix(str(doc or "")))
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
        if len(normalized) >= limit:
            break
    return normalized


def build_query_items(
    *,
    main_query: str,
    sub_queries: list[str] | None = None,
    sub_query_specs: list[dict[str, object]] | None = None,
    variants: list[str] | None = None,
    hyde_doc: str | None = None,
    hyde_docs: list[str] | None = None,
    hyde_note: str | None = None,
) -> list[QueryItem]:
    """为检索与溯源构建统一的查询集合。

    - `main_query` is always retained as the first query item.
    - Sub-queries and variants can coexist (complex path keeps both).
    - HyDE is included as a *dense-only* query item by default.
    - When `hyde_docs` has multiple candidates, retrieval may aggregate embeddings.
    """

    main = _normalize_whitespace(main_query)
    if not main:
        return []

    items: list[QueryItem] = [
        {
            "kind": "main",
            "query": main,
            "use_dense": True,
            "use_bm25": True,
        }
    ]

    if sub_queries:
        specs_by_query: dict[str, dict[str, object]] = {}
        for spec in sub_query_specs or []:
            if not isinstance(spec, dict):
                continue
            query_value = _normalize_whitespace(str(spec.get("query") or ""))
            if not query_value:
                continue
            specs_by_query.setdefault(query_value.casefold(), spec)
        for idx, q in enumerate(sub_queries):
            qn = _normalize_whitespace(q)
            if qn:
                spec = specs_by_query.get(qn.casefold()) or {}
                raw_tags_obj = spec.get("coverage_tags")
                raw_tags: list[object] = (
                    raw_tags_obj if isinstance(raw_tags_obj, list) else []
                )
                coverage_tags = [
                    _normalize_whitespace(str(tag))
                    for tag in raw_tags
                    if _normalize_whitespace(str(tag))
                ][:6]
                priority = spec.get("priority")
                if not isinstance(priority, int):
                    priority = idx + 1
                purpose = _normalize_whitespace(str(spec.get("purpose") or ""))
                items.append(
                    {
                        "kind": "subquery",
                        "query": qn,
                        "index": idx,
                        "origin": "decomposition",
                        "subquery_id": f"sq_{idx + 1}",
                        "priority": max(1, min(int(priority), 8)),
                        "coverage_tags": coverage_tags,
                        "purpose": purpose,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )
    if variants:
        for idx, q in enumerate(variants):
            qn = _normalize_whitespace(q)
            if qn:
                items.append(
                    {
                        "kind": "variant",
                        "query": qn,
                        "index": idx,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )

    hyde_candidates: list[str] = []
    if hyde_docs:
        hyde_candidates.extend(
            [str(value) for value in hyde_docs if str(value).strip()]
        )
    if hyde_doc:
        hyde_candidates.append(hyde_doc)
    hyde_candidates = _normalize_hyde_documents(hyde_candidates)
    if hyde_candidates:
        hyde_item: QueryItem = {
            "kind": "hyde",
            "query": hyde_candidates[0],
            "index": 0,
            "use_dense": True,
            "use_bm25": False,
            "hyde_queries": hyde_candidates,
            "hyde_aggregation": HYDE_AGGREGATION,
        }
        if hyde_note:
            hyde_item["note"] = _normalize_whitespace(hyde_note)
        items.append(hyde_item)

    # 做全局去重，避免重复检索调用，并保留首次出现的项。
    deduped: list[QueryItem] = []
    seen: set[tuple[str, bool, bool]] = set()
    for item in items:
        query = item.get("query") or ""
        use_dense = bool(item.get("use_dense", True))
        use_bm25 = bool(item.get("use_bm25", True))
        key = (query, use_dense, use_bm25)
        if query and key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


