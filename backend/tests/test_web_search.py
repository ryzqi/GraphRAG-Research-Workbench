import json
import sys
import types

import httpx
import pytest

from app.agents.tools.web_search import (
    WebSearchArgs,
    WebSearchClient,
    build_web_search_tool,
)
from app.core.settings import Settings


def _install_tavily_stub(monkeypatch: pytest.MonkeyPatch):
    class DummyAsyncTavilyClient:
        init_calls = 0
        instances = []

        def __init__(self, api_key: str) -> None:
            type(self).init_calls += 1
            self.api_key = api_key
            self.calls = []
            type(self).instances.append(self)

        async def search(
            self, *, query: str, max_results: int, topic: str, include_answer: bool
        ):
            self.calls.append(
                {
                    "query": query,
                    "max_results": max_results,
                    "topic": topic,
                    "include_answer": include_answer,
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
                ]
            }

    module = types.ModuleType("tavily")
    module.AsyncTavilyClient = DummyAsyncTavilyClient
    monkeypatch.setitem(sys.modules, "tavily", module)
    return DummyAsyncTavilyClient


def test_web_search_args_accepts_academic() -> None:
    args = WebSearchArgs(query="x", search_type="academic", max_results=5)
    assert args.search_type == "academic"


@pytest.mark.asyncio
async def test_web_search_reuses_client_and_maps_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = _install_tavily_stub(monkeypatch)
    settings = Settings(web_search_api_key="test-key")
    client = WebSearchClient(settings)

    await client.search("q1", max_results=2, search_type="academic")
    await client.search("q2", max_results=3, search_type="finance")
    await client.search("q3", max_results=4, search_type="news")

    assert dummy.init_calls == 1
    instance = dummy.instances[0]
    assert instance.api_key == "test-key"
    assert [call["topic"] for call in instance.calls] == ["general", "finance", "news"]
    assert all(call["include_answer"] is False for call in instance.calls)
    assert [call["max_results"] for call in instance.calls] == [2, 3, 4]


@pytest.mark.asyncio
async def test_web_search_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_tavily_stub(monkeypatch)
    settings = Settings(web_search_api_key="")
    client = WebSearchClient(settings)

    with pytest.raises(RuntimeError, match="WEB_SEARCH_API_KEY"):
        await client.search("q")


@pytest.mark.asyncio
async def test_web_search_tool_handles_payment_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyAsyncTavilyClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        async def search(
            self, *, query: str, max_results: int, topic: str, include_answer: bool
        ):
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
    result = await tool.ainvoke(
        {"query": "q", "max_results": 5, "search_type": "general"}
    )
    payload = json.loads(result)

    assert payload["total_found"] == 0
    assert payload["results"] == []
    assert payload["error"]["code"] == "WEB_SEARCH_PAYMENT_REQUIRED"
    assert payload["error"]["status_code"] == 402
