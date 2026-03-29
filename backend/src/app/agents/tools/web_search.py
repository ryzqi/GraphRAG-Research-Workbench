"""网页搜索、抽取、爬取与研究工具。
基于 Tavily 实现联网搜索能力。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, TYPE_CHECKING

import httpx
from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, Field

from app.agents.tools.web_search_providers import (
    NormalizedSearchResult,
    ProviderSearchReport,
    ProviderSearchResponse,
    extract_domain,
)
from app.agents.tools.web_search_providers.jina_provider import JinaReadProvider
from app.agents.tools.web_search_providers.searxng_provider import SearxngSearchProvider
from app.core.settings import Settings
from app.integrations.http_client import create_http_client
from app.integrations.redis_client import RedisClient
from app.search.web.contracts import ReadProvider, SearchRetriever
from app.search.web.pipeline import WebSearchPipeline
from app.search.web.retrievers import (
    ProviderSearchRetriever,
    SearchProviderBackend,
    SearxngSearchRetriever,
    TavilySearchRetriever,
)

if TYPE_CHECKING:
    from tavily import AsyncTavilyClient

try:
    from tavily import (
        BadRequestError,
        ForbiddenError,
        InvalidAPIKeyError,
        TimeoutError as TavilyTimeoutError,
        UsageLimitExceededError,
    )
except Exception:  # pragma: no cover - 依赖缺失时不阻断导入
    BadRequestError = ForbiddenError = InvalidAPIKeyError = TavilyTimeoutError = UsageLimitExceededError = ()  # type: ignore

logger = logging.getLogger(__name__)

TAVILY_BASE_URL = "https://api.tavily.com"

AsyncCall = Callable[[], Awaitable[dict[str, Any]]]


class WebSearchArgs(BaseModel):
    """网页搜索参数。"""

    query: str = Field(..., description="搜索查询")
    max_results: int | None = Field(
        default=None, ge=1, le=20, description="最大结果数（默认走配置）"
    )
    search_type: Literal["general", "news", "finance", "academic"] = Field(
        default="general", description="搜索类型（general/news/finance/academic）"
    )
    search_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="搜索深度（basic/advanced）"
    )
    time_range: str | None = Field(
        default=None, description="时间范围（day/week/month/year）"
    )
    include_domains: list[str] | None = Field(
        default=None, description="仅包含域名列表"
    )
    exclude_domains: list[str] | None = Field(
        default=None, description="排除域名列表"
    )
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_answer: bool | Literal["basic", "advanced"] | None = Field(
        default=None, description="是否返回答案（可选 basic/advanced）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_image_descriptions: bool | None = Field(
        default=None, description="是否返回图片描述"
    )
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")
    auto_parameters: bool | None = Field(
        default=None, description="是否启用自动参数优化"
    )
    timeout_seconds: float | None = Field(
        default=None, ge=1, description="单次请求超时（秒）"
    )


class JinaReadArgs(BaseModel):
    """Jina 页面读取参数。"""

    url: str = Field(..., description="要读取的绝对 URL")
    timeout_seconds: float | None = Field(
        default=None, ge=1, description="单次请求超时（秒）"
    )


class WebExtractArgs(BaseModel):
    """网页抽取参数。"""

    urls: list[str] = Field(..., description="目标 URL 列表")
    extract_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="抽取深度（basic/advanced）"
    )
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")
    timeout_seconds: float | None = Field(
        default=None, ge=1, description="单次请求超时（秒）"
    )


class WebCrawlArgs(BaseModel):
    """网页爬取参数。"""

    url: str = Field(..., description="起始 URL")
    limit: int | None = Field(default=None, ge=1, le=100, description="最大抓取数量")
    max_depth: int | None = Field(default=None, ge=1, le=10, description="最大深度")
    max_breadth: int | None = Field(
        default=None, ge=1, le=100, description="最大广度"
    )
    select_paths: list[str] | None = Field(
        default=None, description="包含路径前缀"
    )
    exclude_paths: list[str] | None = Field(
        default=None, description="排除路径前缀"
    )
    select_domains: list[str] | None = Field(
        default=None, description="包含域名列表"
    )
    exclude_domains: list[str] | None = Field(
        default=None, description="排除域名列表"
    )
    extract_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="抽取深度（basic/advanced）"
    )
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")
    timeout_seconds: float | None = Field(
        default=None, ge=1, description="单次请求超时（秒）"
    )


class WebResearchArgs(BaseModel):
    """网页研究参数。"""

    query: str = Field(..., description="研究问题")
    search_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="搜索深度（basic/advanced）"
    )
    max_results: int | None = Field(
        default=None, ge=1, le=50, description="最大结果数"
    )
    time_range: str | None = Field(
        default=None, description="时间范围（day/week/month/year）"
    )
    topic: Literal["general", "news", "finance"] | None = Field(
        default=None, description="研究主题（general/news/finance）"
    )
    include_domains: list[str] | None = Field(
        default=None, description="仅包含域名列表"
    )
    exclude_domains: list[str] | None = Field(
        default=None, description="排除域名列表"
    )
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_answer: bool | Literal["basic", "advanced"] | None = Field(
        default=None, description="是否返回答案（可选 basic/advanced）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_image_descriptions: bool | None = Field(
        default=None, description="是否返回图片描述"
    )
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")
    auto_parameters: bool | None = Field(
        default=None, description="是否启用自动参数优化"
    )
    output_format: Literal["report", "structured"] | None = Field(
        default=None, description="输出格式（report/structured）"
    )
    output_schema: dict | str | None = Field(
        default=None, description="结构化输出 schema（JSON）"
    )
    citation_format: Literal["markdown", "text"] | None = Field(
        default=None, description="引用格式（markdown/text）"
    )
    model: str | None = Field(default=None, description="研究模型")
    stream: bool | None = Field(default=None, description="是否启用流式输出")
    poll_interval_seconds: float | None = Field(
        default=None, ge=0, description="轮询间隔（秒）"
    )
    timeout_seconds: float | None = Field(
        default=None, ge=1, description="研究超时（秒）"
    )


@dataclass(slots=True)
class _TavilyCallContext:
    query: str | None
    parameters: dict[str, Any]
    cache_key: str | None = None


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


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _format_tavily_error(
    exc: Exception,
    *,
    code_prefix: str,
    default_message: str,
) -> dict:
    status_code = _extract_status_code(exc)
    code = f"{code_prefix}_UPSTREAM_ERROR"
    message = default_message
    retryable = False

    if isinstance(exc, UsageLimitExceededError):
        code = f"{code_prefix}_RATE_LIMITED"
        message = "请求过于频繁或额度不足，请稍后重试"
        retryable = True
    elif isinstance(exc, InvalidAPIKeyError) or (
        isinstance(exc, RuntimeError) and "WEB_SEARCH_API_KEY" in str(exc)
    ):
        code = f"{code_prefix}_AUTH_ERROR"
        message = "WEB_SEARCH_API_KEY 无效或未配置"
    elif isinstance(exc, ForbiddenError):
        code = f"{code_prefix}_FORBIDDEN"
        message = "请求被拒绝，可能需要提升权限"
    elif isinstance(exc, BadRequestError):
        code = f"{code_prefix}_BAD_REQUEST"
        message = "请求参数错误"
    elif isinstance(exc, TavilyTimeoutError) or isinstance(exc, httpx.TimeoutException):
        code = f"{code_prefix}_TIMEOUT"
        message = "请求超时，请稍后重试"
        retryable = True
    elif status_code == 402:
        code = f"{code_prefix}_PAYMENT_REQUIRED"
        message = "Tavily 返回 402 Payment Required，可能余额不足或套餐到期"
    elif status_code == 429:
        code = f"{code_prefix}_RATE_LIMITED"
        message = "请求过于频繁，请稍后重试"
        retryable = True
    elif status_code in {401, 403}:
        code = f"{code_prefix}_AUTH_ERROR"
        message = "鉴权失败，请检查 WEB_SEARCH_API_KEY"
    elif status_code is not None and status_code >= 500:
        retryable = True

    detail = str(exc).strip()
    error = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if status_code is not None:
        error["status_code"] = status_code
    if detail:
        error["detail"] = detail[:300]
    return error


def _format_validation_error(code_prefix: str, message: str) -> dict:
    return {
        "code": f"{code_prefix}_BAD_REQUEST",
        "message": message,
        "retryable": False,
    }


def _normalize_domains(domains: Iterable[str] | None) -> list[str] | None:
    if not domains:
        return None
    normalized = [d.strip() for d in domains if d and d.strip()]
    return normalized or None


def _filter_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None and v != []}


def _format_search_type(search_type: str) -> str:
    if search_type in {"news", "finance"}:
        return search_type
    return "general"


def _should_degrade_search(payload: dict[str, Any], exc: Exception) -> bool:
    if (
        payload.get("search_depth") != "advanced"
        and not payload.get("include_raw_content")
        and not payload.get("include_images")
        and not payload.get("include_image_descriptions")
    ):
        return False
    if isinstance(exc, TavilyTimeoutError) or isinstance(exc, httpx.TimeoutException):
        return True
    status_code = _extract_status_code(exc)
    return status_code in {408, 429, 500, 502, 503, 504}


def _degrade_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    degraded = dict(payload)
    degraded["search_depth"] = "basic"
    degraded["include_raw_content"] = False
    degraded["include_images"] = False
    degraded["include_image_descriptions"] = False
    degraded["include_answer"] = False
    return degraded


def _normalize_results(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in items:
        results.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
                "published_at": item.get("published_date") or item.get("published_at"),
                "raw_content": item.get("raw_content"),
                "images": item.get("images"),
                "favicon": item.get("favicon"),
                "source": item.get("source") or "tavily",
            }
        )
    return results


def _build_output(
    *,
    context: _TavilyCallContext,
    results: list[dict[str, Any]],
    elapsed_ms: int,
    cache_hit: bool,
    total_found: int | None = None,
    usage: dict[str, Any] | None = None,
    request_id: str | None = None,
    answer: str | None = None,
    report: str | None = None,
    error: dict | None = None,
) -> dict[str, Any]:
    output = {
        "query": context.query,
        "parameters": context.parameters,
        "total_found": total_found if total_found is not None else len(results),
        "results": results,
        "error": error,
        "usage": usage,
        "request_id": request_id,
        "elapsed_ms": elapsed_ms,
        "cache_hit": cache_hit,
    }
    if answer:
        output["answer"] = answer
    if report:
        output["report"] = report
    return output


class TavilyGateway:
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
        self._rate_limiter = _LocalRateLimiter(settings.web_search_rate_limit_per_minute)
        self._semaphore = (
            asyncio.Semaphore(settings.web_search_max_concurrency)
            if settings.web_search_max_concurrency > 0
            else None
        )
        self._redis = redis
        self._http_client = http_client
        self._client: AsyncTavilyClient | None = None

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
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        async def _call_once() -> dict[str, Any]:
            await self._rate_limiter.acquire()
            if self._semaphore is None:
                if timeout_seconds:
                    return await asyncio.wait_for(func(), timeout=timeout_seconds)
                return await func()
            async with self._semaphore:
                if timeout_seconds:
                    return await asyncio.wait_for(func(), timeout=timeout_seconds)
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
        if isinstance(exc, TavilyTimeoutError) or isinstance(exc, httpx.TimeoutException):
            return True
        status_code = _extract_status_code(exc)
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
            filtered = _filter_none(kwargs)
        else:
            filtered = {
                k: v
                for k, v in kwargs.items()
                if k in sig.parameters and v is not None
            }
        return await method(**filtered)

    async def _call_tavily_http(
        self,
        *,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("未配置 WEB_SEARCH_API_KEY，无法使用 Tavily Web 工具")
        url = f"{TAVILY_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._http_client is None:
            client = create_http_client(self._settings)
            try:
                response = await client.request(
                    method,
                    url,
                    json=json_payload,
                    headers=headers,
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            finally:
                await client.aclose()
        response = await self._http_client.request(
            method,
            url,
            json=json_payload,
            headers=headers,
            timeout=timeout_seconds,
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
        payload = _filter_none(
            {
                "query": args.query,
                "max_results": max_results,
                "topic": _format_search_type(args.search_type),
                "search_depth": search_depth,
                "time_range": time_range,
                "include_domains": _normalize_domains(args.include_domains),
                "exclude_domains": _normalize_domains(args.exclude_domains),
                "include_raw_content": args.include_raw_content,
                "include_answer": args.include_answer,
                "include_images": args.include_images,
                "include_image_descriptions": args.include_image_descriptions,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
                "auto_parameters": auto_parameters,
            }
        )
        context = _TavilyCallContext(query=args.query, parameters=payload)
        cache_key = self._cache_key("search", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        timeout = args.timeout_seconds or settings.web_search_timeout_seconds
        start = time.perf_counter()
        try:
            response = await self._run_with_policy(
                lambda: self._call_tavily("search", **payload, timeout=timeout),
                timeout_seconds=timeout,
            )
        except Exception as exc:
            if _should_degrade_search(payload, exc):
                degraded_payload = _degrade_search_payload(payload)
                cache_key = self._cache_key("search", degraded_payload)
                context.parameters = degraded_payload
                try:
                    response = await self._run_with_policy(
                        lambda: self._call_tavily(
                            "search", **degraded_payload, timeout=timeout
                        ),
                        timeout_seconds=timeout,
                    )
                except Exception as exc2:
                    error = _format_tavily_error(
                        exc2,
                        code_prefix="WEB_SEARCH",
                        default_message="Web 搜索暂时不可用，请稍后重试",
                    )
                    output = _build_output(
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
                error = _format_tavily_error(
                    exc,
                    code_prefix="WEB_SEARCH",
                    default_message="Web 搜索暂时不可用，请稍后重试",
                )
                output = _build_output(
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

        results = _normalize_results(response.get("results", []))
        output = _build_output(
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
        payload = _filter_none(
            {
                "urls": args.urls,
                "extract_depth": extract_depth,
                "include_raw_content": args.include_raw_content,
                "include_images": args.include_images,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
            }
        )
        context = _TavilyCallContext(query=",".join(args.urls), parameters=payload)
        cache_key = self._cache_key("extract", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        timeout = args.timeout_seconds or settings.web_search_timeout_seconds
        start = time.perf_counter()
        try:
            response = await self._run_with_policy(
                lambda: self._call_tavily("extract", **payload, timeout=timeout),
                timeout_seconds=timeout,
            )
            results = _normalize_results(response.get("results", []))
            if not results and response.get("content"):
                results = _normalize_results([response])
            output = _build_output(
                context=context,
                results=results,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                total_found=response.get("total_results") or response.get("total_found"),
                usage=response.get("usage"),
                request_id=response.get("request_id"),
            )
        except Exception as exc:
            error = _format_tavily_error(
                exc,
                code_prefix="WEB_EXTRACT",
                default_message="Web 抽取暂时不可用，请稍后重试",
            )
            output = _build_output(
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
        payload = _filter_none(
            {
                "url": args.url,
                "limit": args.limit or settings.web_crawl_default_limit,
                "max_depth": args.max_depth or settings.web_crawl_default_max_depth,
                "max_breadth": args.max_breadth or settings.web_crawl_default_max_breadth,
                "select_paths": _normalize_domains(args.select_paths),
                "exclude_paths": _normalize_domains(args.exclude_paths),
                "select_domains": _normalize_domains(args.select_domains),
                "exclude_domains": _normalize_domains(args.exclude_domains),
                "extract_depth": extract_depth,
                "include_raw_content": args.include_raw_content,
                "include_images": args.include_images,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
            }
        )
        context = _TavilyCallContext(query=args.url, parameters=payload)
        cache_key = self._cache_key("crawl", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        timeout = args.timeout_seconds or settings.web_search_timeout_seconds
        start = time.perf_counter()
        try:
            response = await self._run_with_policy(
                lambda: self._call_tavily("crawl", **payload, timeout=timeout),
                timeout_seconds=timeout,
            )
            results = _normalize_results(response.get("results", []))
            output = _build_output(
                context=context,
                results=results,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                total_found=response.get("total_results") or response.get("total_found"),
                usage=response.get("usage"),
                request_id=response.get("request_id"),
            )
        except Exception as exc:
            error = _format_tavily_error(
                exc,
                code_prefix="WEB_CRAWL",
                default_message="Web 爬取暂时不可用，请稍后重试",
            )
            output = _build_output(
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
        payload = _filter_none(
            {
                "query": args.query,
                "search_depth": args.search_depth or settings.web_search_default_search_depth,
                "max_results": args.max_results or settings.web_search_default_max_results,
                "time_range": args.time_range or settings.web_search_default_time_range,
                "topic": args.topic,
                "include_domains": _normalize_domains(args.include_domains),
                "exclude_domains": _normalize_domains(args.exclude_domains),
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
                "output_format": args.output_format or settings.web_research_output_format,
                "output_schema": args.output_schema or settings.web_research_output_schema,
                "citation_format": args.citation_format
                or settings.web_research_citation_format,
                "model": args.model or settings.web_research_model,
                "stream": args.stream,
            }
        )
        context = _TavilyCallContext(query=args.query, parameters=payload)
        cache_key = self._cache_key("research", payload)
        context.cache_key = cache_key
        cached = await self._read_cache(cache_key)
        if cached:
            cached["cache_hit"] = True
            cached["elapsed_ms"] = 0
            return cached

        timeout = args.timeout_seconds or settings.web_research_timeout_seconds
        poll_interval = (
            args.poll_interval_seconds or settings.web_research_poll_interval_seconds
        )
        start = time.perf_counter()
        try:
            try:
                create_response = await self._run_with_policy(
                    lambda: self._call_tavily("research", **payload),
                    timeout_seconds=timeout,
                )
            except RuntimeError:
                create_response = await self._run_with_policy(
                    lambda: self._call_tavily_http(
                        method="POST",
                        path="/research",
                        json_payload=payload,
                        timeout_seconds=timeout,
                    ),
                    timeout_seconds=timeout,
                )

            task_id = create_response.get("id")
            status = create_response.get("status")
            result = create_response
            if task_id and status not in {"completed", "failed", "error"}:
                result = await self._poll_research(task_id, timeout, poll_interval)

            results = _normalize_results(result.get("result", {}).get("sources", []))
            report = None
            if isinstance(result.get("result"), dict):
                report = result.get("result", {}).get("content")
            output = _build_output(
                context=context,
                results=results,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                cache_hit=False,
                usage=result.get("usage"),
                request_id=result.get("request_id"),
                report=report,
            )
        except Exception as exc:
            error = _format_tavily_error(
                exc,
                code_prefix="WEB_RESEARCH",
                default_message="Web 研究暂时不可用，请稍后重试",
            )
            output = _build_output(
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
        self, task_id: str, timeout_seconds: float, poll_interval: float
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            if time.monotonic() >= deadline:
                raise httpx.TimeoutException("Research polling timeout")
            try:
                response = await self._call_tavily("get_research", id=task_id)
            except RuntimeError:
                response = await self._call_tavily_http(
                    method="GET", path=f"/research/{task_id}"
                )
            status = response.get("status")
            if status in {"completed", "failed", "error"}:
                return response
            await asyncio.sleep(poll_interval)


class WebSearchClient(TavilyGateway):
    """兼容旧接口的别名。"""


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
                    "timeout_seconds": kwargs.get("timeout_seconds"),
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


def has_web_search_provider(settings: Settings) -> bool:
    return bool(settings.web_search_api_key or settings.searxng_search_enabled)


def has_web_extract_provider(settings: Settings) -> bool:
    return bool(settings.web_search_api_key)


def has_jina_read_provider(settings: Settings) -> bool:
    return bool(settings.jina_read_enabled and settings.jina_read_base_url)


def build_search_providers(
    settings: Settings,
    *,
    redis: RedisClient | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> list[SearchProviderBackend]:
    providers: list[SearchProviderBackend] = []
    if settings.web_search_api_key:
        providers.append(
            TavilySearchProviderAdapter(
                WebSearchClient(settings, redis=redis, http_client=http_client)
            )
        )
    if settings.searxng_search_enabled:
        providers.append(
            SearxngSearchProvider(settings=settings, http_client=http_client)
        )
    return providers


def build_search_retrievers(
    providers: list[SearchProviderBackend],
) -> list[SearchRetriever]:
    retrievers: list[SearchRetriever] = []
    for provider in providers:
        provider_name = str(getattr(provider, "provider_name", "")).strip()
        if provider_name == "tavily":
            retrievers.append(TavilySearchRetriever(provider))
            continue
        if provider_name == "searxng":
            retrievers.append(SearxngSearchRetriever(provider))
            continue
        retrievers.append(ProviderSearchRetriever(provider))
    return retrievers


def _build_web_search_error_output(
    *,
    query: str | None,
    parameters: dict[str, Any],
    error: dict[str, Any],
) -> dict[str, Any]:
    output = _build_output(
        context=_TavilyCallContext(query=query, parameters=parameters),
        results=[],
        elapsed_ms=0,
        cache_hit=False,
        error=error,
    )
    output["provider_reports"] = []
    output["merged_count"] = 0
    return output


def build_web_search_tool(
    settings: Settings,
    *,
    redis: RedisClient | None = None,
    http_client: httpx.AsyncClient | None = None,
    search_providers: list[SearchProviderBackend] | None = None,
    read_provider: ReadProvider | None = None,
) -> BaseTool:
    """构建 Web 搜索工具。"""
    resolved_search_providers = (
        search_providers
        if search_providers is not None
        else build_search_providers(
            settings,
            redis=redis,
            http_client=http_client,
        )
    )
    resolved_read_provider = (
        read_provider
        if read_provider is not None
        else (
            JinaReadProvider(settings=settings, http_client=http_client)
            if has_jina_read_provider(settings)
            else None
        )
    )
    retrievers = build_search_retrievers(resolved_search_providers)
    pipeline = WebSearchPipeline(
        retrievers=retrievers,
        read_provider=resolved_read_provider,
    )

    async def _search(**kwargs: object) -> str:
        try:
            args = WebSearchArgs(**kwargs)
        except Exception:
            error = _format_validation_error("WEB_SEARCH", "Web 搜索参数错误")
            return json.dumps(
                _build_web_search_error_output(
                    query=None,
                    parameters={},
                    error=error,
                ),
                ensure_ascii=False,
            )
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
        normalized_include_domains = _normalize_domains(args.include_domains)
        normalized_exclude_domains = _normalize_domains(args.exclude_domains)
        timeout_seconds = args.timeout_seconds or settings.web_search_timeout_seconds
        parameters = _filter_none(
            {
                "query": args.query,
                "max_results": max_results,
                "search_type": args.search_type,
                "search_depth": search_depth,
                "time_range": time_range,
                "include_domains": normalized_include_domains,
                "exclude_domains": normalized_exclude_domains,
                "include_raw_content": args.include_raw_content,
                "include_answer": args.include_answer,
                "include_images": args.include_images,
                "include_image_descriptions": args.include_image_descriptions,
                "include_favicon": args.include_favicon,
                "include_usage": include_usage,
                "auto_parameters": auto_parameters,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not retrievers:
            error = {
                "code": "WEB_SEARCH_PROVIDER_NOT_CONFIGURED",
                "message": "未配置可用的 Web 搜索 provider",
                "retryable": False,
            }
            return json.dumps(
                _build_web_search_error_output(
                    query=args.query,
                    parameters=parameters,
                    error=error,
                ),
                ensure_ascii=False,
            )
        output = await pipeline.search(
            query=args.query,
            max_results=max_results,
            search_type=args.search_type,
            search_depth=search_depth,
            time_range=time_range,
            include_domains=normalized_include_domains,
            exclude_domains=normalized_exclude_domains,
            include_raw_content=args.include_raw_content,
            include_answer=args.include_answer,
            include_images=args.include_images,
            include_image_descriptions=args.include_image_descriptions,
            include_favicon=args.include_favicon,
            include_usage=include_usage,
            auto_parameters=auto_parameters,
            timeout_seconds=timeout_seconds,
        )
        output["parameters"] = parameters
        output["total_found"] = len(output.get("results", []))
        output.setdefault("usage", None)
        output.setdefault("request_id", None)
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "web_search",
        description=(
            "从互联网做综合搜索，聚合 Tavily 与 SearXNG 结果，并可用 jina_read 对高相关结果做正文增强。"
        ),
        args_schema=WebSearchArgs,
    )(_search)


def build_jina_read_tool(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
    jina_read_provider: JinaReadProvider | Any | None = None,
) -> BaseTool:
    """构建 Jina 页面读取工具。"""
    provider = jina_read_provider or JinaReadProvider(
        settings=settings,
        http_client=http_client,
    )

    async def _read(**kwargs: object) -> str:
        try:
            args = JinaReadArgs(**kwargs)
        except Exception:
            error = _format_validation_error("JINA_READ", "Jina 页面读取参数错误")
            return json.dumps(
                {
                    "url": None,
                    "title": "",
                    "content": "",
                    "error": error,
                },
                ensure_ascii=False,
            )
        output = await provider.read(
            url=args.url,
            timeout_seconds=args.timeout_seconds,
        )
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "jina_read",
        description="读取指定 URL 的页面正文，适合在综合搜索摘要不足时补充获取正文内容。",
        args_schema=JinaReadArgs,
    )(_read)


def build_web_extract_tool(
    settings: Settings,
    *,
    redis: RedisClient | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> BaseTool:
    """构建 Web 抽取工具。"""
    client = WebSearchClient(settings, redis=redis, http_client=http_client)

    async def _extract(**kwargs: object) -> str:
        try:
            args = WebExtractArgs(**kwargs)
        except Exception:
            error = _format_validation_error("WEB_EXTRACT", "Web 抽取参数错误")
            return json.dumps(
                _build_output(
                    context=_TavilyCallContext(query=None, parameters={}),
                    results=[],
                    elapsed_ms=0,
                    cache_hit=False,
                    error=error,
                ),
                ensure_ascii=False,
            )
        output = await client.extract(args)
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "web_extract",
        description="抽取指定 URL 的正文与结构化信息，支持多 URL 与原文/图片开关。",
        args_schema=WebExtractArgs,
    )(_extract)


def build_web_crawl_tool(
    settings: Settings,
    *,
    redis: RedisClient | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> BaseTool:
    """构建 Web 爬取工具。"""
    client = WebSearchClient(settings, redis=redis, http_client=http_client)

    async def _crawl(**kwargs: object) -> str:
        try:
            args = WebCrawlArgs(**kwargs)
        except Exception:
            error = _format_validation_error("WEB_CRAWL", "Web 爬取参数错误")
            return json.dumps(
                _build_output(
                    context=_TavilyCallContext(query=None, parameters={}),
                    results=[],
                    elapsed_ms=0,
                    cache_hit=False,
                    error=error,
                ),
                ensure_ascii=False,
            )
        output = await client.crawl(args)
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "web_crawl",
        description="从站点起始 URL 爬取内容，可限定深度/广度/路径/域名。",
        args_schema=WebCrawlArgs,
    )(_crawl)


def build_web_research_tool(
    settings: Settings,
    *,
    redis: RedisClient | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> BaseTool:
    """构建 Web 研究工具。"""
    client = WebSearchClient(settings, redis=redis, http_client=http_client)

    async def _research(**kwargs: object) -> str:
        try:
            args = WebResearchArgs(**kwargs)
        except Exception:
            error = _format_validation_error("WEB_RESEARCH", "Web 研究参数错误")
            return json.dumps(
                _build_output(
                    context=_TavilyCallContext(query=None, parameters={}),
                    results=[],
                    elapsed_ms=0,
                    cache_hit=False,
                    error=error,
                ),
                ensure_ascii=False,
            )
        output = await client.research(args)
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "web_research",
        description="面向复杂主题的研究任务，可生成报告或结构化输出。",
        args_schema=WebResearchArgs,
    )(_research)
