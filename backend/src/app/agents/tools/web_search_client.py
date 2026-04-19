"""网页搜索 Tavily client 与 provider 适配。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Callable

import httpx

from app.agents.tools.web_search_models import (
    WebCrawlArgs,
    WebExtractArgs,
    WebResearchArgs,
    WebSearchArgs,
)
from app.agents.tools.web_search_providers import (
    NormalizedSearchResult,
    ProviderSearchReport,
    ProviderSearchResponse,
    extract_domain,
)
from app.core.settings import Settings
from app.integrations.http_client import create_http_client
from app.integrations.redis_client import RedisClient
from app.agents.tools.web_search_utils import (
    TavilyCallContext,
    TavilyTimeoutError,
    UsageLimitExceededError,
    build_output,
    degrade_search_payload,
    extract_status_code,
    filter_none,
    format_search_type,
    format_tavily_error,
    normalize_domains,
    normalize_results,
    should_degrade_search,
)

if TYPE_CHECKING:
    from tavily import AsyncTavilyClient

logger = logging.getLogger(__name__)

AsyncCall = Callable[[], Awaitable[dict[str, Any]]]


class _LocalRateLimiter:
    """进程内简易限流器（按分钟滑动窗口）。"""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()

    async def acquire(self) -> None:
        if self._max <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] >= 60:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._max:
                sleep_for = 60 - (now - self._timestamps[0])
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] >= 60:
                self._timestamps.popleft()
            self._timestamps.append(time.monotonic())


class WebSearchClient:
    """统一 Tavily 请求策略。"""

    def __init__(
        self,
        settings: Settings,
        redis: RedisClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._api_key = settings.web_search_api_key
        self._cache_enabled = settings.web_search_cache_enabled
        self._cache_ttl = settings.web_search_cache_ttl_seconds
        self._retry_max = settings.web_search_retry_max
        self._retry_backoff = settings.web_search_retry_backoff_seconds
        self._rate_limiter = _LocalRateLimiter(
            settings.web_search_rate_limit_per_minute
        )
        self._semaphore = (
            asyncio.Semaphore(settings.web_search_max_concurrency)
            if settings.web_search_max_concurrency > 0
            else None
        )
        self._redis = redis
        self._http_client = http_client
        self._client: AsyncTavilyClient | None = None

    def _resolve_tavily_base_url(self) -> str:
        base_url = self._settings.web_search_provider.tavily_base_url.strip().rstrip("/")
        if not base_url:
            raise RuntimeError("未配置 TAVILY_BASE_URL，无法访问 Tavily HTTP API")
        return base_url

    def _get_client(self) -> "AsyncTavilyClient":
        try:
            from tavily import AsyncTavilyClient
        except ImportError as exc:
            raise RuntimeError(
                "未安装 tavily-python 依赖，无法使用 Tavily Web 工具（请安装 tavily-python 并配置 WEB_SEARCH_API_KEY）"
            ) from exc

        if not self._api_key:
            raise RuntimeError("未配置 WEB_SEARCH_API_KEY，无法使用 Tavily Web 工具")

        if self._client is None:
            self._client = AsyncTavilyClient(self._api_key)
        return self._client

    def _http_request_timeout(self, client: httpx.AsyncClient) -> httpx.Timeout:
        return client.timeout

    def _sdk_timeout_seconds(self, *, default_seconds: float | None) -> float:
        read_timeout = float(self._settings.http_timeout_read_seconds)
        if default_seconds is None:
            return read_timeout
        return max(float(default_seconds), read_timeout)

    def _cache_key(self, prefix: str, payload: dict[str, Any]) -> str:
        fingerprint = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        raw = f"{prefix}:{fingerprint}"
        return f"tavily:{hashlib.md5(raw.encode()).hexdigest()}"

    def _get_redis(self) -> RedisClient | None:
        if not self._cache_enabled:
            return None
        return self._redis

    async def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        redis = self._get_redis()
        if not redis:
            return None
        try:
            cached = await redis.get(cache_key)
        except Exception as exc:  # pragma: no cover
            logger.warning("Web 搜索缓存读取失败，跳过缓存", extra={"error": str(exc)})
            return None
        if not cached:
            return None
        try:
            return json.loads(cached)
        except json.JSONDecodeError:  # pragma: no cover
            return None

    async def _write_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        redis = self._get_redis()
        if not redis:
            return
        try:
            await redis.set(
                cache_key, json.dumps(payload, ensure_ascii=False), ex=self._cache_ttl
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Web 搜索缓存写入失败，跳过缓存", extra={"error": str(exc)})

    async def _run_with_policy(
        self,
        func: AsyncCall,
    ) -> dict[str, Any]:
        async def _call_once() -> dict[str, Any]:
            await self._rate_limiter.acquire()
            if self._semaphore is None:
                return await func()
            async with self._semaphore:
                return await func()

        return await self._run_with_retries(_call_once)

    async def _run_with_retries(self, func: AsyncCall) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return await func()
            except Exception as exc:
                if attempt >= self._retry_max or not self._is_retryable(exc):
                    raise
                backoff = self._retry_backoff * (2**attempt)
                await asyncio.sleep(backoff)
                attempt += 1

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, UsageLimitExceededError):
            return True
        if isinstance(exc, TavilyTimeoutError) or isinstance(
            exc, httpx.TimeoutException
        ):
            return True
        status_code = extract_status_code(exc)
        if status_code in {408, 425, 429, 500, 502, 503, 504}:
            return True
        return False

    async def _call_tavily(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        client = self._get_client()
        method = getattr(client, method_name, None)
        if method is None:
            raise RuntimeError(f"Tavily SDK 不支持 {method_name}")

        sig = inspect.signature(method)
        accepts_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if accepts_kwargs:
            filtered = {
                k: v for k, v in kwargs.items() if v is not None or k == "timeout"
            }
        else:
            filtered = {
                k: v
                for k, v in kwargs.items()
                if k in sig.parameters and (v is not None or k == "timeout")
            }
        return await method(**filtered)

    async def _call_tavily_http(
        self,
        *,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("未配置 WEB_SEARCH_API_KEY，无法使用 Tavily Web 工具")
        url = f"{self._resolve_tavily_base_url()}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._http_client is None:
            client = create_http_client(self._settings)
            timeout = self._http_request_timeout(client)
            try:
                response = await client.request(
                    method,
                    url,
                    json=json_payload,
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()
            finally:
                await client.aclose()
        timeout = self._http_request_timeout(self._http_client)
        response = await self._http_client.request(
            method,
            url,
            json=json_payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    async def search(self, args: WebSearchArgs) -> dict[str, Any]:
        settings = self._settings
        max_results = args.max_results or settings.web_search_default_max_results
        search_depth = args.search_depth or settings.web_search_default_search_depth
        time_range = args.time_range or settings.web_search_default_time_range
        include_usage = (
            args.include_usage
            if args.include_usage is not None
            else settings.web_search_include_usage
        )
        auto_parameters = (
            args.auto_parameters
            if args.auto_parameters is not None
            else settings.web_search_auto_parameters
        )
        payload = filter_none(
            {
                "query": args.query,
                "max_results": max_results,
                "topic": format_search_type(args.search_type),
                "search_depth": search_depth,
                "time_range": time_range,
                "include_domains": normalize_domains(args.include_domains),
                "exclude_domains": normalize_domains(args.exclude_domains),
                "include_raw_content": args.include_raw_content,
                "include_answer": args.include_answer,
                "include_images": args.include_images,
                "include_image_descriptions": args.include_image_descriptions,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
                "auto_parameters": auto_parameters,
            }
        )
        context = TavilyCallContext(query=args.query, parameters=payload)
        cache_key = self._cache_key("search", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        start = time.perf_counter()
        try:
            response = await self._run_with_policy(
                lambda: self._call_tavily_http(
                    method="POST",
                    path="/search",
                    json_payload=payload,
                ),
            )
        except Exception as exc:
            if should_degrade_search(payload, exc):
                degraded_payload = degrade_search_payload(payload)
                cache_key = self._cache_key("search", degraded_payload)
                context.parameters = degraded_payload
                try:
                    response = await self._run_with_policy(
                        lambda: self._call_tavily_http(
                            method="POST",
                            path="/search",
                            json_payload=degraded_payload,
                        ),
                    )
                except Exception as exc2:
                    error = format_tavily_error(
                        exc2,
                        code_prefix="WEB_SEARCH",
                        default_message="Web 搜索暂时不可用，请稍后重试",
                    )
                    output = build_output(
                        context=context,
                        results=[],
                        elapsed_ms=int((time.perf_counter() - start) * 1000),
                        cache_hit=False,
                        error=error,
                    )
                    logger.warning(
                        "Web 搜索失败",
                        extra={
                            "error_code": error.get("code"),
                            "status_code": error.get("status_code"),
                            "search_depth": search_depth,
                        },
                        exc_info=exc2,
                    )
                    return output
            else:
                error = format_tavily_error(
                    exc,
                    code_prefix="WEB_SEARCH",
                    default_message="Web 搜索暂时不可用，请稍后重试",
                )
                output = build_output(
                    context=context,
                    results=[],
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    cache_hit=False,
                    error=error,
                )
                logger.warning(
                    "Web 搜索失败",
                    extra={
                        "error_code": error.get("code"),
                        "status_code": error.get("status_code"),
                        "search_depth": search_depth,
                    },
                    exc_info=exc,
                )
                return output

        results = normalize_results(response.get("results", []))
        output = build_output(
            context=context,
            results=results,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            cache_hit=False,
            total_found=response.get("total_results") or response.get("total_found"),
            usage=response.get("usage"),
            request_id=response.get("request_id"),
            answer=response.get("answer"),
        )

        await self._write_cache(cache_key, output)
        return output

    async def extract(self, args: WebExtractArgs) -> dict[str, Any]:
        settings = self._settings
        extract_depth = args.extract_depth or settings.web_extract_default_depth
        include_usage = (
            args.include_usage
            if args.include_usage is not None
            else settings.web_search_include_usage
        )
        payload = filter_none(
            {
                "urls": args.urls,
                "extract_depth": extract_depth,
                "include_raw_content": args.include_raw_content,
                "include_images": args.include_images,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
            }
        )
        context = TavilyCallContext(query=",".join(args.urls), parameters=payload)
        cache_key = self._cache_key("extract", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        start = time.perf_counter()
        try:
            response = await self._run_with_policy(
                lambda: self._call_tavily(
                    "extract",
                    **payload,
                    timeout=self._sdk_timeout_seconds(default_seconds=30.0),
                ),
            )
            results = normalize_results(response.get("results", []))
            if not results and response.get("content"):
                results = normalize_results([response])
            output = build_output(
                context=context,
                results=results,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                total_found=response.get("total_results")
                or response.get("total_found"),
                usage=response.get("usage"),
                request_id=response.get("request_id"),
            )
        except Exception as exc:
            error = format_tavily_error(
                exc,
                code_prefix="WEB_EXTRACT",
                default_message="Web 抽取暂时不可用，请稍后重试",
            )
            output = build_output(
                context=context,
                results=[],
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                error=error,
            )
            logger.warning(
                "Web 抽取失败",
                extra={
                    "error_code": error.get("code"),
                    "status_code": error.get("status_code"),
                    "extract_depth": extract_depth,
                },
                exc_info=exc,
            )
            return output

        await self._write_cache(cache_key, output)
        return output

    async def crawl(self, args: WebCrawlArgs) -> dict[str, Any]:
        settings = self._settings
        extract_depth = args.extract_depth or settings.web_crawl_default_depth
        include_usage = (
            args.include_usage
            if args.include_usage is not None
            else settings.web_search_include_usage
        )
        payload = filter_none(
            {
                "url": args.url,
                "limit": args.limit or settings.web_crawl_default_limit,
                "max_depth": args.max_depth or settings.web_crawl_default_max_depth,
                "max_breadth": args.max_breadth
                or settings.web_crawl_default_max_breadth,
                "select_paths": normalize_domains(args.select_paths),
                "exclude_paths": normalize_domains(args.exclude_paths),
                "select_domains": normalize_domains(args.select_domains),
                "exclude_domains": normalize_domains(args.exclude_domains),
                "extract_depth": extract_depth,
                "include_raw_content": args.include_raw_content,
                "include_images": args.include_images,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
            }
        )
        context = TavilyCallContext(query=args.url, parameters=payload)
        cache_key = self._cache_key("crawl", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        start = time.perf_counter()
        try:
            response = await self._run_with_policy(
                lambda: self._call_tavily(
                    "crawl",
                    **payload,
                    timeout=self._sdk_timeout_seconds(default_seconds=150.0),
                ),
            )
            results = normalize_results(response.get("results", []))
            output = build_output(
                context=context,
                results=results,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                total_found=response.get("total_results")
                or response.get("total_found"),
                usage=response.get("usage"),
                request_id=response.get("request_id"),
            )
        except Exception as exc:
            error = format_tavily_error(
                exc,
                code_prefix="WEB_CRAWL",
                default_message="Web 爬取暂时不可用，请稍后重试",
            )
            output = build_output(
                context=context,
                results=[],
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                error=error,
            )
            logger.warning(
                "Web 爬取失败",
                extra={
                    "error_code": error.get("code"),
                    "status_code": error.get("status_code"),
                    "extract_depth": extract_depth,
                },
                exc_info=exc,
            )
            return output

        await self._write_cache(cache_key, output)
        return output

    async def research(self, args: WebResearchArgs) -> dict[str, Any]:
        settings = self._settings
        include_usage = (
            args.include_usage
            if args.include_usage is not None
            else settings.web_search_include_usage
        )
        payload = filter_none(
            {
                "input": args.query,
                "search_depth": args.search_depth
                or settings.web_search_default_search_depth,
                "max_results": args.max_results
                or settings.web_search_default_max_results,
                "time_range": args.time_range or settings.web_search_default_time_range,
                "topic": args.topic,
                "include_domains": normalize_domains(args.include_domains),
                "exclude_domains": normalize_domains(args.exclude_domains),
                "include_raw_content": args.include_raw_content,
                "include_answer": args.include_answer,
                "include_images": args.include_images,
                "include_image_descriptions": args.include_image_descriptions,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
                "auto_parameters": (
                    args.auto_parameters
                    if args.auto_parameters is not None
                    else settings.web_search_auto_parameters
                ),
                "output_format": args.output_format
                or settings.web_research_output_format,
                "output_schema": args.output_schema
                or settings.web_research_output_schema,
                "citation_format": args.citation_format
                or settings.web_research_citation_format,
                "model": args.model or settings.web_research_model,
                "stream": args.stream,
            }
        )
        context = TavilyCallContext(query=args.query, parameters=payload)
        cache_key = self._cache_key("research", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        poll_interval = (
            args.poll_interval_seconds or settings.web_research_poll_interval_seconds
        )
        start = time.perf_counter()
        try:
            try:
                create_response = await self._run_with_policy(
                    lambda: self._call_tavily(
                        "research",
                        **payload,
                        timeout=self._sdk_timeout_seconds(default_seconds=None),
                    ),
                )
            except RuntimeError:
                create_response = await self._run_with_policy(
                    lambda: self._call_tavily_http(
                        method="POST",
                        path="/research",
                        json_payload=payload,
                    ),
                )

            request_id = create_response.get("request_id")
            status = create_response.get("status")
            result = create_response
            if request_id and status not in {"completed", "failed", "error"}:
                result = await self._poll_research(request_id, poll_interval)

            raw_sources = result.get("sources")
            results = normalize_results(
                raw_sources if isinstance(raw_sources, list) else []
            )
            report = (
                result.get("content")
                if isinstance(result.get("content"), str)
                else None
            )
            output = build_output(
                context=context,
                results=results,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                usage=result.get("usage"),
                request_id=result.get("request_id"),
                report=report,
            )
        except Exception as exc:
            error = format_tavily_error(
                exc,
                code_prefix="WEB_RESEARCH",
                default_message="Web 研究暂时不可用，请稍后重试",
            )
            output = build_output(
                context=context,
                results=[],
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                error=error,
            )
            logger.warning(
                "Web 研究失败",
                extra={
                    "error_code": error.get("code"),
                    "status_code": error.get("status_code"),
                },
                exc_info=exc,
            )
            return output

        await self._write_cache(cache_key, output)
        return output

    async def _poll_research(
        self, request_id: str, poll_interval: float
    ) -> dict[str, Any]:
        while True:
            try:
                response = await self._call_tavily(
                    "get_research", request_id=request_id
                )
            except RuntimeError:
                response = await self._call_tavily_http(
                    method="GET", path=f"/research/{request_id}"
                )
            status = response.get("status")
            if status in {"completed", "failed", "error"}:
                return response
            await asyncio.sleep(poll_interval)



class TavilySearchProviderAdapter:
    provider_name = "tavily"

    def __init__(self, client: WebSearchClient) -> None:
        self._client = client

    async def search(self, **kwargs: Any) -> ProviderSearchResponse:
        output = await self._client.search(
            WebSearchArgs.model_validate(
                {
                    "query": kwargs.get("query"),
                    "max_results": kwargs.get("max_results"),
                    "search_type": kwargs.get("search_type") or "general",
                    "search_depth": kwargs.get("search_depth"),
                    "time_range": kwargs.get("time_range"),
                    "include_domains": kwargs.get("include_domains"),
                    "exclude_domains": kwargs.get("exclude_domains"),
                    "include_raw_content": kwargs.get("include_raw_content"),
                    "include_answer": kwargs.get("include_answer"),
                    "include_images": kwargs.get("include_images"),
                    "include_image_descriptions": kwargs.get(
                        "include_image_descriptions"
                    ),
                    "include_favicon": kwargs.get("include_favicon"),
                    "include_usage": kwargs.get("include_usage"),
                    "auto_parameters": kwargs.get("auto_parameters"),
                }
            )
        )
        results = [
            NormalizedSearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("snippet") or item.get("content") or ""),
                source_provider="tavily",
                score=item.get("score")
                if isinstance(item.get("score"), int | float)
                else None,
                published_at=item.get("published_at"),
                domain=extract_domain(str(item.get("url") or "")),
            )
            for item in output.get("results", [])
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        ]
        return ProviderSearchResponse(
            provider="tavily",
            results=results,
            report=ProviderSearchReport(
                provider="tavily",
                ok=not bool(output.get("error")),
                result_count=len(results),
                elapsed_ms=int(output.get("elapsed_ms") or 0),
                error=output.get("error"),
            ),
        )
