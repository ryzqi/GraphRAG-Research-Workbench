"""网页搜索 provider / tool 构建器。"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
from langchain.tools import BaseTool, tool as lc_tool

from app.agents.tools.web_search_client import (
    TavilySearchProviderAdapter,
    WebSearchClient,
)
from app.agents.tools.web_search_models import (
    JinaReadArgs,
    WebCrawlArgs,
    WebExtractArgs,
    WebSearchArgs,
)
from app.agents.tools.web_search_providers.jina_provider import JinaReadProvider
from app.agents.tools.web_search_providers.searxng_provider import SearxngSearchProvider
from app.agents.tools.web_search_utils import (
    TavilyCallContext,
    build_output,
    filter_none,
    format_validation_error,
    normalize_domains,
)
from app.core.settings import Settings
from app.integrations.redis_client import RedisClient
from app.search.web.contracts import ReadProvider, SearchRetriever
from app.search.web.pipeline import WebSearchPipeline
from app.search.web.retrievers import (
    ProviderSearchRetriever,
    SearchProviderBackend,
    SearxngSearchRetriever,
    TavilySearchRetriever,
)

_READ_PROVIDER_UNSET = object()


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
            retrievers.append(cast(SearchRetriever, TavilySearchRetriever(provider)))
            continue
        if provider_name == "searxng":
            retrievers.append(cast(SearchRetriever, SearxngSearchRetriever(provider)))
            continue
        retrievers.append(cast(SearchRetriever, ProviderSearchRetriever(provider)))
    return retrievers


def _build_web_search_error_output(
    *,
    query: str | None,
    parameters: dict[str, Any],
    error: dict[str, Any],
) -> dict[str, Any]:
    output = build_output(
        context=TavilyCallContext(query=query, parameters=parameters),
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
    read_provider: ReadProvider | None | object = _READ_PROVIDER_UNSET,
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
    if read_provider is _READ_PROVIDER_UNSET:
        resolved_read_provider: ReadProvider | None = (
            cast(
                ReadProvider,
                JinaReadProvider(settings=settings, http_client=http_client),
            )
            if has_jina_read_provider(settings)
            else None
        )
    else:
        resolved_read_provider = cast(ReadProvider | None, read_provider)
    retrievers = build_search_retrievers(resolved_search_providers)
    pipeline = WebSearchPipeline(
        retrievers=retrievers,
        read_provider=resolved_read_provider,
    )

    async def _search(**kwargs: object) -> str:
        try:
            args = WebSearchArgs.model_validate(kwargs)
        except Exception:
            error = format_validation_error("WEB_SEARCH", "Web 搜索参数错误")
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
        normalized_include_domains = normalize_domains(args.include_domains)
        normalized_exclude_domains = normalize_domains(args.exclude_domains)
        parameters = filter_none(
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
            args = JinaReadArgs.model_validate(kwargs)
        except Exception:
            error = format_validation_error("JINA_READ", "Jina 页面读取参数错误")
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
            args = WebExtractArgs.model_validate(kwargs)
        except Exception:
            error = format_validation_error("WEB_EXTRACT", "Web 抽取参数错误")
            return json.dumps(
                build_output(
                    context=TavilyCallContext(query=None, parameters={}),
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
            args = WebCrawlArgs.model_validate(kwargs)
        except Exception:
            error = format_validation_error("WEB_CRAWL", "Web 爬取参数错误")
            return json.dumps(
                build_output(
                    context=TavilyCallContext(query=None, parameters={}),
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
