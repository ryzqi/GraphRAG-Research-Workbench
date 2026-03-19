from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.utils.text_sanitization import sanitize_visible_text


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", sanitize_visible_text(text)).strip()


def _sanitize_query_text(text: str) -> str:
    return _normalize_whitespace(text).strip("`\"' ")


def is_semantically_complete(query: str) -> bool:
    value = _sanitize_query_text(query)
    if not value:
        return False
    if value.startswith(("的", "了", "和", "与")):
        return False

    tokens = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", value)
    if not tokens:
        return False
    if len(tokens) == 1 and re.fullmatch(r"[A-Za-z0-9_]{2,}", tokens[0]):
        return False
    return True


def should_enable_hyde(
    *,
    strategy: str,
    recall_risk: str,
    first_pass_failed: bool,
) -> bool:
    _ = strategy
    return bool(first_pass_failed and str(recall_risk).strip().lower() == "high")


def should_enable_broadening_retry(*, first_pass_failed: bool) -> bool:
    return bool(first_pass_failed)


def should_enable_retry_rewrite(*, first_pass_failed: bool) -> bool:
    return bool(first_pass_failed)


@dataclass(slots=True)
class QueryValidationResult:
    items: list[dict[str, Any]]
    rejections: dict[str, int]


def build_validated_query_items(
    *,
    normalized_query: str,
    planned_items: list[dict[str, Any]] | None,
) -> QueryValidationResult:
    canonical = _sanitize_query_text(normalized_query)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    rejections = {
        "fragment_rejected": 0,
        "duplicate_rejected": 0,
        "empty_rejected": 0,
    }

    seed_items = planned_items or []
    if canonical and not any(
        _sanitize_query_text(str(item.get("query") or "")) == canonical
        and str(item.get("kind") or "") == "main"
        for item in seed_items
        if isinstance(item, dict)
    ):
        seed_items = [{"kind": "main", "query": canonical}, *seed_items]

    for raw in seed_items:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "paraphrase").strip() or "paraphrase"
        query = _sanitize_query_text(str(raw.get("query") or ""))
        if not query:
            rejections["empty_rejected"] += 1
            continue
        if kind != "main" and not is_semantically_complete(query):
            rejections["fragment_rejected"] += 1
            continue

        key = (kind, query.casefold())
        if key in seen:
            rejections["duplicate_rejected"] += 1
            continue
        seen.add(key)
        items.append(
            {
                **raw,
                "kind": kind,
                "query": query,
                "semantic_complete": is_semantically_complete(query),
            }
        )

    return QueryValidationResult(items=items, rejections=rejections)
