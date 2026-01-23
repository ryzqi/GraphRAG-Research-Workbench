import json
import sys
import types

import httpx
import pytest

from app.agents.tools.web_search import (
    WebCrawlArgs,
    WebExtractArgs,
    WebResearchArgs,
    WebSearchArgs,
    WebSearchClient,
    build_web_crawl_tool,
    build_web_extract_tool,
    build_web_research_tool,
    build_web_search_tool,
)
from app.core.settings import Settings


class DummyRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def _install_tavily_stub(monkeypatch: pytest.MonkeyPatch):
    class DummyAsyncTavilyClient:
        init_calls = 0
        instances = []

        def __init__(self, api_key: str) -> None:
            type(self).init_calls += 1
            self.api_key = api_key
            self.search_calls = []
            self.extract_calls = []
            self.crawl_calls = []
            self.research_calls = []
            self.research_status_calls = []
            type(self).instances.append(self)

        async def search(
            self,
            *,
            query: str,
            max_results: int,
            topic: str,
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
            timeout: float | None = None,
        ):
            self.search_calls.append(
                {
                    "query": query,
                    "max_results": max_results,
                    "topic": topic,
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
                    "timeout": timeout,
                }
            )
            return {
                "results": [
                    {
                        "title": "t",
                        "url": "u",
                        "content": "c",
                        "published_date": "2024-01-01",
                    }
                ],
                "request_id": "req-search",
                "usage": {"credits": 1},
                "total_results": 1,
            }

        async def extract(
            self,
            *,
            urls: list[str],
            extract_depth: str | None = None,
            include_raw_content: bool | str | None = None,
            include_images: bool | None = None,
            include_favicon: bool | None = None,
            include_usage: bool | None = None,
            timeout: float | None = None,
        ):
            self.extract_calls.append(
                {
                    "urls": urls,
                    "extract_depth": extract_depth,
                    "include_raw_content": include_raw_content,
                    "include_images": include_images,
                    "include_favicon": include_favicon,
                    "include_usage": include_usage,
                    "timeout": timeout,
                }
            )
            return {
                "results": [
                    {"url": urls[0], "title": "t", "content": "c", "raw_content": "rc"}
                ],
                "request_id": "req-extract",
            }

        async def crawl(
            self,
            *,
            url: str,
            limit: int | None = None,
            max_depth: int | None = None,
            max_breadth: int | None = None,
            select_paths: list[str] | None = None,
            exclude_paths: list[str] | None = None,
            select_domains: list[str] | None = None,
            exclude_domains: list[str] | None = None,
            extract_depth: str | None = None,
            include_raw_content: bool | str | None = None,
            include_images: bool | None = None,
            include_favicon: bool | None = None,
            include_usage: bool | None = None,
            timeout: float | None = None,
        ):
            self.crawl_calls.append(
                {
                    "url": url,
                    "limit": limit,
                    "max_depth": max_depth,
                    "max_breadth": max_breadth,
                    "select_paths": select_paths,
                    "exclude_paths": exclude_paths,
                    "select_domains": select_domains,
                    "exclude_domains": exclude_domains,
                    "extract_depth": extract_depth,
                    "include_raw_content": include_raw_content,
                    "include_images": include_images,
                    "include_favicon": include_favicon,
                    "include_usage": include_usage,
                    "timeout": timeout,
                }
            )
            return {
                "results": [{"url": url, "title": "t", "content": "c"}],
                "request_id": "req-crawl",
                "total_results": 1,
            }

        async def research(self, **kwargs: object):
            self.research_calls.append(kwargs)
            return {"id": "task-1", "status": "pending"}

        async def get_research(self, *, id: str):
            self.research_status_calls.append(id)
            return {
                "id": id,
                "status": "completed",
                "request_id": "req-research",
                "result": {
                    "content": "report",
                    "sources": [{"title": "t", "url": "u", "content": "c"}],
                },
            }

    module = types.ModuleType("tavily")
    module.AsyncTavilyClient = DummyAsyncTavilyClient
    monkeypatch.setitem(sys.modules, "tavily", module)
    return DummyAsyncTavilyClient


def test_web_search_args_accepts_academic() -> None:
    args = WebSearchArgs(query="x", search_type="academic", max_results=5)
    assert args.search_type == "academic"


@pytest.mark.asyncio
async def test_web_search_maps_params_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = _install_tavily_stub(monkeypatch)
    settings = Settings(
        web_search_api_key="test-key",
        web_search_cache_enabled=True,
        web_search_include_usage=True,
    )
    redis = DummyRedis()
    client = WebSearchClient(settings, redis=redis)

    args = WebSearchArgs(
        query="q1",
        max_results=2,
        search_type="academic",
        search_depth="advanced",
        time_range="week",
        include_domains=["example.com"],
        include_raw_content="markdown",
        include_images=True,
        auto_parameters=False,
    )
    output1 = await client.search(args)
    output2 = await client.search(args)

    assert output1["cache_hit"] is False
    assert output2["cache_hit"] is True
    assert output1["request_id"] == "req-search"
    assert output1["usage"] == {"credits": 1}

    instance = dummy.instances[0]
    call = instance.search_calls[0]
    assert call["topic"] == "general"
    assert call["search_depth"] == "advanced"
    assert call["time_range"] == "week"
    assert call["include_domains"] == ["example.com"]
    assert call["include_raw_content"] == "markdown"
    assert call["include_images"] is True
    assert call["auto_parameters"] is False
    assert call["include_usage"] is True


@pytest.mark.asyncio
async def test_web_search_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_tavily_stub(monkeypatch)
    settings = Settings(web_search_api_key="")
    client = WebSearchClient(settings)

    output = await client.search(WebSearchArgs(query="q"))
    assert output["results"] == []
    assert output["error"]["code"] == "WEB_SEARCH_AUTH_ERROR"


@pytest.mark.asyncio
async def test_web_search_tool_handles_payment_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyAsyncTavilyClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        async def search(self, *, query: str, max_results: int, topic: str, timeout=None):
            request = httpx.Request("POST", "https://api.tavily.com/search")
            response = httpx.Response(status_code=402, request=request)
            raise httpx.HTTPStatusError(
                "402 Payment Required", request=request, response=response
            )

    module = types.ModuleType("tavily")
    module.AsyncTavilyClient = DummyAsyncTavilyClient
    monkeypatch.setitem(sys.modules, "tavily", module)

    settings = Settings(web_search_api_key="test-key")
    tool = build_web_search_tool(settings)
    result = await tool.ainvoke({"query": "q", "max_results": 5, "search_type": "general"})
    payload = json.loads(result)

    assert payload["total_found"] == 0
    assert payload["results"] == []
    assert payload["error"]["code"] == "WEB_SEARCH_PAYMENT_REQUIRED"
    assert payload["error"]["status_code"] == 402


@pytest.mark.asyncio
async def test_web_extract_tool_normalizes_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_tavily_stub(monkeypatch)
    settings = Settings(web_search_api_key="test-key")
    tool = build_web_extract_tool(settings)
    result = await tool.ainvoke(
        WebExtractArgs(urls=["https://example.com"]).model_dump()
    )
    payload = json.loads(result)

    assert payload["request_id"] == "req-extract"
    assert payload["total_found"] == 1
    assert payload["results"][0]["raw_content"] == "rc"


@pytest.mark.asyncio
async def test_web_crawl_tool_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = _install_tavily_stub(monkeypatch)
    settings = Settings(
        web_search_api_key="test-key",
        web_crawl_default_limit=7,
        web_crawl_default_max_depth=2,
        web_crawl_default_max_breadth=9,
    )
    tool = build_web_crawl_tool(settings)
    await tool.ainvoke(WebCrawlArgs(url="https://example.com").model_dump())

    instance = dummy.instances[0]
    call = instance.crawl_calls[0]
    assert call["limit"] == 7
    assert call["max_depth"] == 2
    assert call["max_breadth"] == 9


@pytest.mark.asyncio
async def test_web_research_tool_polls_and_returns_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_tavily_stub(monkeypatch)
    settings = Settings(
        web_search_api_key="test-key",
        web_research_poll_interval_seconds=0,
        web_research_timeout_seconds=5,
    )
    tool = build_web_research_tool(settings)
    result = await tool.ainvoke(WebResearchArgs(query="x").model_dump())
    payload = json.loads(result)

    assert payload["request_id"] == "req-research"
    assert payload["report"] == "report"
    assert payload["total_found"] == 1
