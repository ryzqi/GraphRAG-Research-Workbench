import sys
import types

import pytest

from app.agents.tools.web_search import WebSearchArgs, WebSearchClient
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
