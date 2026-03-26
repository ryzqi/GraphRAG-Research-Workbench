"""SearXNG provider 适配。"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.settings import Settings
from app.integrations.http_client import create_http_client

from .base import (
    NormalizedSearchResult,
    ProviderSearchReport,
    ProviderSearchResponse,
    build_provider_error,
    extract_domain,
)


def _apply_domain_filters(
    query: str,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    parts = [query.strip()]
    for domain in include_domains or []:
        normalized = str(domain).strip()
        if normalized:
            parts.append(f"site:{normalized}")
    for domain in exclude_domains or []:
        normalized = str(domain).strip()
        if normalized:
            parts.append(f"-site:{normalized}")
    return " ".join(part for part in parts if part)


def _extract_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


class SearxngSearchProvider:
    provider_name = "searxng"

    def __init__(
        self,
        *,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client

    async def _request_json(
        self,
        *,
        params: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> Any:
        url = f"{self._settings.searxng_search_base_url.rstrip('/')}/search"
        timeout = timeout_seconds or self._settings.searxng_timeout_seconds
        headers = {"Accept": "application/json"}
        if self._http_client is None:
            client = create_http_client(self._settings)
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()
            finally:
                await client.aclose()
        response = await self._http_client.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    async def search(
        self,
        *,
        query: str,
        max_results: int = 5,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        timeout_seconds: float | None = None,
        **_: Any,
    ) -> ProviderSearchResponse:
        start = time.perf_counter()
        filtered_query = _apply_domain_filters(
            query,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        params: dict[str, Any] = {
            "q": filtered_query,
            "format": "json",
            "pageno": 1,
        }
        if time_range:
            params["time_range"] = time_range
        if self._settings.searxng_default_categories:
            params["categories"] = ",".join(self._settings.searxng_default_categories)
        if self._settings.searxng_default_language:
            params["language"] = self._settings.searxng_default_language
        if self._settings.searxng_default_engines:
            params["engines"] = ",".join(self._settings.searxng_default_engines)

        try:
            payload = await self._request_json(
                params=params,
                timeout_seconds=timeout_seconds,
            )
            raw_items = payload.get("results") if isinstance(payload, dict) else []
            results = [
                NormalizedSearchResult(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or item.get("snippet") or ""),
                    source_provider="searxng",
                    score=item.get("score")
                    if isinstance(item.get("score"), int | float)
                    else None,
                    published_at=item.get("publishedDate")
                    or item.get("published_at"),
                    domain=extract_domain(str(item.get("url") or "")),
                )
                for item in raw_items
                if isinstance(item, dict) and str(item.get("url") or "").strip()
            ][: max(max_results, 0)]
            report = ProviderSearchReport(
                provider="searxng",
                ok=True,
                result_count=len(results),
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                error=None,
            )
            return ProviderSearchResponse(
                provider="searxng",
                results=results,
                report=report,
            )
        except Exception as exc:
            error = build_provider_error(
                code="SEARXNG_SEARCH_UPSTREAM_ERROR",
                message="SearXNG 搜索暂时不可用，请稍后重试",
                retryable=isinstance(exc, (httpx.TimeoutException, httpx.HTTPStatusError)),
                detail=str(exc),
                status_code=_extract_status_code(exc),
            )
            return ProviderSearchResponse(
                provider="searxng",
                results=[],
                report=ProviderSearchReport(
                    provider="searxng",
                    ok=False,
                    result_count=0,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    error=error,
                ),
            )
