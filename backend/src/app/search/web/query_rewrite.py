"""网页搜索查询改写。"""

from __future__ import annotations

from datetime import datetime

from app.config.policy_loader import load_search_policy
from app.search.web.contracts import SearchQueryPlan


def _current_year() -> int:
    return datetime.now().year


def build_search_query_plan(
    query: str,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> SearchQueryPlan:
    normalized = str(query or "").strip()
    rewritten: list[str] = []
    if normalized:
        rewritten.append(normalized)

    lowered = normalized.lower()
    query_rewrite_policy = load_search_policy().query_rewrite
    if include_domains:
        for domain in include_domains:
            candidate = str(domain or "").strip()
            if candidate:
                rewritten.append(f"site:{candidate} {normalized}")
    else:
        for keyword, domains in query_rewrite_policy.auto_include_domains.items():
            normalized_keyword = str(keyword or "").strip().lower()
            if not normalized_keyword or normalized_keyword not in lowered:
                continue
            for domain in domains:
                candidate = str(domain or "").strip()
                if not candidate or f"site:{candidate.lower()}" in lowered:
                    continue
                rewritten.append(f"site:{candidate} {normalized}")

    if (
        query_rewrite_policy.append_current_year_suffix
        and any(
            str(keyword or "").strip().lower() in lowered
            for keyword in query_rewrite_policy.freshness_keywords
        )
        and str(_current_year()) not in normalized
    ):
        rewritten.append(f"{normalized} {_current_year()}")

    if exclude_domains:
        domain_tokens = " ".join(
            f"-site:{candidate}"
            for domain in exclude_domains
            if (candidate := str(domain or "").strip())
        ).strip()
        if domain_tokens:
            rewritten = [
                " ".join(part for part in [item, domain_tokens] if part).strip()
                for item in rewritten
            ]

    deduped: list[str] = []
    seen: set[str] = set()
    for item in rewritten:
        compact = " ".join(item.split())
        key = compact.lower()
        if not compact or key in seen:
            continue
        seen.add(key)
        deduped.append(compact)

    return SearchQueryPlan(
        original_query=normalized,
        rewritten_queries=deduped or [normalized],
    )
