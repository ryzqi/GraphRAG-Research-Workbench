"""网页搜索查询改写。"""

from __future__ import annotations

from app.search.web.contracts import SearchQueryPlan

_FRESHNESS_KEYWORDS = (
    "最新",
    "当前",
    "最近",
    "today",
    "latest",
    "current",
    "news",
    "release",
    "changelog",
)


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
    if include_domains:
        for domain in include_domains:
            candidate = str(domain or "").strip()
            if candidate:
                rewritten.append(f"site:{candidate} {normalized}")
    elif "langchain" in lowered and "site:docs.langchain.com" not in lowered:
        rewritten.append(f"site:docs.langchain.com {normalized}")

    if any(keyword in lowered for keyword in _FRESHNESS_KEYWORDS) and "2026" not in normalized:
        rewritten.append(f"{normalized} 2026")

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
