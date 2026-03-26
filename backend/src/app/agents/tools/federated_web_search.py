"""联邦网页搜索聚合服务。"""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from app.agents.tools.web_search_providers import (
    NormalizedSearchResult,
    ProviderSearchResponse,
    build_provider_error,
    canonicalize_url,
    extract_domain,
)

_LOW_QUALITY_ENRICH_DOMAIN_SUFFIXES = (
    "linkedin.com",
    "x.com",
    "twitter.com",
    "medium.com",
)
_ENRICHMENT_SNIPPET_MIN_LENGTH = 180
_PROVIDER_CANDIDATE_MULTIPLIER = 3
_PROVIDER_CANDIDATE_MAX_RESULTS = 10


class SearchProvider(Protocol):
    provider_name: str

    async def search(self, **kwargs: Any) -> ProviderSearchResponse: ...


class ReadProvider(Protocol):
    provider_name: str

    async def read(
        self,
        *,
        url: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]: ...


def _filter_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in payload.items() if value is not None and value != []
    }


def _build_snippet_from_content(content: str, *, limit: int = 400) -> str:
    normalized = " ".join(str(content or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


class FederatedWebSearchService:
    """并发执行多路 provider 搜索，并完成去重与聚合。"""

    def __init__(
        self,
        *,
        providers: Sequence[SearchProvider],
        read_provider: ReadProvider | None = None,
        enrich_top_results: int = 2,
    ) -> None:
        self._providers = list(providers)
        self._read_provider = read_provider
        self._enrich_top_results = max(enrich_top_results, 0)

    async def search(
        self,
        *,
        query: str,
        max_results: int = 5,
        search_type: str | None = None,
        search_depth: str | None = None,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        include_raw_content: bool | str | None = None,
        include_answer: bool | str | None = None,
        include_images: bool | None = None,
        include_image_descriptions: bool | None = None,
        include_favicon: bool | None = None,
        include_usage: bool | None = None,
        auto_parameters: bool | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        provider_max_results = self._get_provider_candidate_budget(max_results)
        parameters = _filter_none(
            {
                "query": query,
                "max_results": max_results,
                "search_type": search_type,
                "search_depth": search_depth,
                "time_range": time_range,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
                "include_raw_content": include_raw_content,
                "include_answer": include_answer,
                "include_images": include_images,
                "include_image_descriptions": include_image_descriptions,
                "include_favicon": include_favicon,
                "include_usage": include_usage,
                "auto_parameters": auto_parameters,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not self._providers:
            return self._build_output(
                query=query,
                parameters=parameters,
                results=[],
                provider_reports=[],
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                error=build_provider_error(
                    code="WEB_SEARCH_PROVIDER_NOT_CONFIGURED",
                    message="未配置可用的 Web 搜索 provider",
                    retryable=False,
                ),
            )

        responses = await asyncio.gather(
            *[
                self._search_provider(
                    provider,
                    query=query,
                    max_results=provider_max_results,
                    search_type=search_type,
                    search_depth=search_depth,
                    time_range=time_range,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    include_raw_content=include_raw_content,
                    include_answer=include_answer,
                    include_images=include_images,
                    include_image_descriptions=include_image_descriptions,
                    include_favicon=include_favicon,
                    include_usage=include_usage,
                    auto_parameters=auto_parameters,
                    timeout_seconds=timeout_seconds,
                )
                for provider in self._providers
            ]
        )
        provider_reports = [
            response.report.model_dump(mode="json") for response in responses
        ]
        merged_results = self._merge_results(
            responses,
            query=query,
            max_results=max_results,
        )
        merged_results, read_report = await self._enrich_results(
            merged_results,
            include_raw_content=include_raw_content,
            timeout_seconds=timeout_seconds,
        )
        if read_report is not None:
            provider_reports.append(read_report)
        any_ok = any(report["ok"] for report in provider_reports)
        error = None
        if not any_ok:
            error = build_provider_error(
                code="WEB_SEARCH_ALL_PROVIDERS_FAILED",
                message="所有 Web 搜索 provider 均失败，请稍后重试",
                retryable=any(
                    bool((report.get("error") or {}).get("retryable"))
                    for report in provider_reports
                ),
            )
        return self._build_output(
            query=query,
            parameters=parameters,
            results=merged_results,
            provider_reports=provider_reports,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            error=error,
        )

    async def _enrich_results(
        self,
        results: list[dict[str, Any]],
        *,
        include_raw_content: bool | str | None,
        timeout_seconds: float | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if self._read_provider is None or self._enrich_top_results <= 0 or not results:
            return results, None

        enriched_results = [dict(item) for item in results]
        start = time.perf_counter()
        candidate_indexes = [
            index
            for index, item in enumerate(enriched_results)
            if self._should_enrich(item)
        ][: self._enrich_top_results]
        if not candidate_indexes:
            return enriched_results, {
                "provider": getattr(self._read_provider, "provider_name", "jina_reader"),
                "ok": True,
                "result_count": 0,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
                "error": None,
            }
        payloads = await asyncio.gather(
            *[
                self._read_provider.read(
                    url=str(enriched_results[index].get("url") or ""),
                    timeout_seconds=timeout_seconds,
                )
                for index in candidate_indexes
            ],
            return_exceptions=True,
        )

        success_count = 0
        first_error: dict[str, Any] | None = None
        should_include_raw_content = bool(include_raw_content)
        for payload_index, payload in enumerate(payloads):
            result_index = candidate_indexes[payload_index]
            if isinstance(payload, Exception):
                if first_error is None:
                    first_error = build_provider_error(
                        code="JINA_READ_ENRICHMENT_ERROR",
                        message="jina_read 结果增强失败",
                        retryable=False,
                        detail=str(payload),
                    )
                continue
            if not isinstance(payload, dict):
                continue
            error = payload.get("error")
            if error:
                if first_error is None and isinstance(error, dict):
                    first_error = error
                continue
            content = str(payload.get("content") or "").strip()
            title = str(payload.get("title") or "").strip()
            if title:
                enriched_results[result_index]["title"] = title
            if content:
                enriched_results[result_index]["snippet"] = _build_snippet_from_content(content)
                if should_include_raw_content:
                    enriched_results[result_index]["raw_content"] = content
            success_count += 1

        report = {
            "provider": getattr(self._read_provider, "provider_name", "jina_reader"),
            "ok": success_count > 0,
            "result_count": success_count,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "error": first_error,
        }
        return enriched_results, report

    def _get_provider_candidate_budget(self, max_results: int) -> int:
        limit = max(max_results, 0)
        if limit <= 0:
            return 0
        return max(
            limit,
            min(limit * _PROVIDER_CANDIDATE_MULTIPLIER, _PROVIDER_CANDIDATE_MAX_RESULTS),
        )

    async def _search_provider(
        self,
        provider: SearchProvider,
        **kwargs: Any,
    ) -> ProviderSearchResponse:
        try:
            return await provider.search(**kwargs)
        except Exception as exc:  # pragma: no cover - provider 自身异常由聚合层兜底
            provider_name = getattr(provider, "provider_name", "tavily")
            return ProviderSearchResponse.model_validate(
                {
                    "provider": provider_name,
                    "results": [],
                    "report": {
                        "provider": provider_name,
                        "ok": False,
                        "result_count": 0,
                        "elapsed_ms": 0,
                        "error": build_provider_error(
                            code=f"{str(provider_name).upper()}_UNHANDLED_ERROR",
                            message=f"{provider_name} provider 执行失败",
                            retryable=False,
                            detail=str(exc),
                        ),
                    },
                }
            )

    def _merge_results(
        self,
        responses: Sequence[ProviderSearchResponse],
        *,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        limit = max(max_results, 0)
        if limit <= 0:
            return []

        query_terms = self._extract_query_terms(query)
        overlap_counts: Counter[str] = Counter()
        unique_items: dict[str, NormalizedSearchResult] = {}
        ordered_keys: list[str] = []
        fallback_index = 0

        for response in responses:
            for item in response.results:
                dedupe_key = canonicalize_url(item.url) or item.url.strip()
                if not dedupe_key:
                    fallback_index += 1
                    dedupe_key = f"__federated_result__:{fallback_index}"
                overlap_counts[dedupe_key] += 1
                existing = unique_items.get(dedupe_key)
                if existing is None:
                    unique_items[dedupe_key] = item
                    ordered_keys.append(dedupe_key)
                    continue
                unique_items[dedupe_key] = self._merge_duplicate_result(existing, item)

        ranked_items = sorted(
            [unique_items[key] for key in ordered_keys],
            key=lambda item: self._score_result(
                item,
                query_terms=query_terms,
                overlap_count=overlap_counts.get(
                    canonicalize_url(item.url) or item.url.strip(),
                    1,
                ),
            ),
            reverse=True,
        )
        return [self._dump_result(item) for item in ranked_items[:limit]]

    def _should_enrich(self, item: dict[str, Any]) -> bool:
        url = str(item.get("url") or "").strip()
        if not url:
            return False
        snippet = str(item.get("snippet") or "").strip()
        domain = self._normalize_domain(item.get("domain") or extract_domain(url))
        if not snippet:
            return True
        if self._matches_domain_suffix(domain, _LOW_QUALITY_ENRICH_DOMAIN_SUFFIXES):
            return True
        return len(snippet) < _ENRICHMENT_SNIPPET_MIN_LENGTH

    def _score_result(
        self,
        item: NormalizedSearchResult,
        *,
        query_terms: set[str],
        overlap_count: int,
    ) -> float:
        base = self._score_value(item.score)
        domain = self._normalize_domain(item.domain or extract_domain(item.url))
        searchable_text = f"{item.title} {item.snippet}".lower()
        lexical_bonus = sum(0.08 for term in query_terms if term in searchable_text)
        overlap_bonus = 0.9 * max(overlap_count - 1, 0)
        freshness_bonus = 0.15 if item.published_at else 0.0
        social_penalty = 0.35 if self._matches_domain_suffix(domain, _LOW_QUALITY_ENRICH_DOMAIN_SUFFIXES) else 0.0
        return base + lexical_bonus + overlap_bonus + freshness_bonus - social_penalty

    def _merge_duplicate_result(
        self,
        existing: NormalizedSearchResult,
        candidate: NormalizedSearchResult,
    ) -> NormalizedSearchResult:
        preferred = candidate
        if self._duplicate_quality(existing) > self._duplicate_quality(candidate):
            preferred = existing

        updates: dict[str, Any] = {}
        if self._score_rank(candidate.score) > self._score_rank(existing.score):
            updates["score"] = candidate.score
        if len(candidate.snippet.strip()) > len(existing.snippet.strip()):
            updates["snippet"] = candidate.snippet
        preferred_title = preferred.title.strip()
        if preferred_title and preferred.title != existing.title:
            updates["title"] = preferred.title
        if preferred.source_provider != existing.source_provider:
            updates["source_provider"] = preferred.source_provider
        if not existing.published_at and candidate.published_at:
            updates["published_at"] = candidate.published_at
        if not existing.domain and candidate.domain:
            updates["domain"] = candidate.domain
        if not updates:
            return existing
        return existing.model_copy(update=updates)

    def _duplicate_quality(
        self,
        item: NormalizedSearchResult,
    ) -> tuple[tuple[int, float], int, int, int]:
        return (
            self._score_rank(item.score),
            len(item.snippet.strip()),
            1 if item.published_at else 0,
            len(item.title.strip()),
        )

    def _score_rank(self, score: float | None) -> tuple[int, float]:
        if score is None:
            return (0, 0.0)
        return (1, float(score))

    def _score_value(self, score: float | None, *, missing: float = 0.0) -> float:
        if score is None:
            return missing
        return float(score)

    def _extract_query_terms(self, query: str) -> set[str]:
        return {
            term
            for term in re.findall(r"[\w-]+", str(query or "").lower())
            if len(term) >= 2
        }

    def _normalize_domain(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _matches_domain_suffix(self, domain: str, suffixes: Sequence[str]) -> bool:
        if not domain:
            return False
        return any(domain == suffix or domain.endswith(f".{suffix}") for suffix in suffixes)

    def _dump_result(self, item: NormalizedSearchResult) -> dict[str, Any]:
        payload = item.model_dump(mode="json")
        payload["source"] = item.source_provider
        if not payload.get("domain"):
            payload["domain"] = extract_domain(item.url)
        return payload

    def _build_output(
        self,
        *,
        query: str,
        parameters: dict[str, Any],
        results: list[dict[str, Any]],
        provider_reports: list[dict[str, Any]],
        elapsed_ms: int,
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "parameters": parameters,
            "total_found": len(results),
            "results": results,
            "provider_reports": provider_reports,
            "merged_count": len(results),
            "error": error,
            "usage": None,
            "request_id": None,
            "elapsed_ms": elapsed_ms,
            "cache_hit": False,
        }
