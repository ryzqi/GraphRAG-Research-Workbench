import json

import pytest
from pydantic import ValidationError

from app.agents.tool_calling.registry import build_research_tool_registry
from app.agents.tools.web_search import (
    JinaReadArgs,
    WebCrawlArgs,
    WebExtractArgs,
    WebResearchArgs,
    WebSearchArgs,
    WebSearchClient,
    build_web_search_tool,
)
from app.agents.tools.web_search_providers.base import (
    NormalizedSearchResult,
    ProviderSearchReport,
    ProviderSearchResponse,
)
from app.core.settings import Settings


def _build_settings() -> Settings:
    return Settings(
        web_search_api_key="tvly-test",
        web_search_cache_enabled=False,
    )


class _RecordingSearchProvider:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs: object) -> ProviderSearchResponse:
        self.calls.append(dict(kwargs))
        query = str(kwargs["query"])
        return ProviderSearchResponse(
            provider=self.provider_name,  # type: ignore[arg-type]
            results=[
                NormalizedSearchResult(
                    title=f"{self.provider_name} result",
                    url=f"https://{self.provider_name}.example.com/{query}",
                    snippet=f"{self.provider_name} snippet",
                    source_provider=self.provider_name,  # type: ignore[arg-type]
                )
            ],
            report=ProviderSearchReport(
                provider=self.provider_name,  # type: ignore[arg-type]
                ok=True,
                result_count=1,
                elapsed_ms=1,
                error=None,
            ),
        )


def test_search_related_models_do_not_expose_timeout_fields() -> None:
    assert "web_search_timeout_seconds" not in Settings.model_fields
    assert "jina_read_timeout_seconds" not in Settings.model_fields
    assert "searxng_timeout_seconds" not in Settings.model_fields
    assert "web_research_timeout_seconds" not in Settings.model_fields

    assert "timeout_seconds" not in WebSearchArgs.model_fields
    assert "timeout_seconds" not in JinaReadArgs.model_fields
    assert "timeout_seconds" not in WebExtractArgs.model_fields
    assert "timeout_seconds" not in WebCrawlArgs.model_fields
    assert "timeout_seconds" not in WebResearchArgs.model_fields


def test_web_research_args_accept_current_tavily_citation_formats() -> None:
    args = WebResearchArgs(query="研究 Tavily 最新 SDK", citation_format="apa")

    assert args.citation_format == "apa"

    with pytest.raises(ValidationError):
        WebResearchArgs(query="研究 Tavily 最新 SDK", citation_format="markdown")


@pytest.mark.asyncio
async def test_research_uses_current_tavily_sdk_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WebSearchClient(_build_settings())
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_call(method_name: str, **kwargs: object) -> dict[str, object]:
        calls.append((method_name, kwargs))
        if method_name == "research":
            return {"request_id": "req-sdk", "status": "pending"}
        if method_name == "get_research":
            return {
                "request_id": "req-sdk",
                "status": "completed",
                "content": "最新 research 报告",
                "sources": [
                    {
                        "title": "官方文档",
                        "url": "https://docs.tavily.com",
                        "content": "Research API 用法",
                    }
                ],
                "usage": {"credits": 1},
            }
        raise AssertionError(f"unexpected method: {method_name}")

    async def _fake_write_cache(key: str, value: dict[str, object]) -> None:
        del key, value

    monkeypatch.setattr(client, "_call_tavily", _fake_call)
    monkeypatch.setattr(client, "_write_cache", _fake_write_cache)

    output = await client.research(
        WebResearchArgs(query="研究 Tavily 最新 SDK", citation_format="apa")
    )

    assert len(calls) == 2
    assert calls[0][0] == "research"
    assert calls[0][1]["input"] == "研究 Tavily 最新 SDK"
    assert "query" not in calls[0][1]
    assert calls[0][1]["citation_format"] == "apa"
    assert calls[1] == ("get_research", {"request_id": "req-sdk"})
    assert output["request_id"] == "req-sdk"
    assert output["report"] == "最新 research 报告"
    assert output["results"] == [
        {
            "title": "官方文档",
            "url": "https://docs.tavily.com",
            "snippet": "Research API 用法",
            "published_at": None,
            "raw_content": None,
            "images": None,
            "favicon": None,
            "source": "tavily",
        }
    ]
    assert output["error"] is None


@pytest.mark.asyncio
async def test_research_http_fallback_uses_current_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WebSearchClient(_build_settings())
    http_calls: list[dict[str, object]] = []

    async def _fake_call(method_name: str, **kwargs: object) -> dict[str, object]:
        del kwargs
        if method_name == "research":
            raise RuntimeError("research unsupported")
        raise AssertionError(f"unexpected method: {method_name}")

    async def _fake_http(
        *,
        method: str,
        path: str,
        json_payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        http_calls.append(
            {
                "method": method,
                "path": path,
                "json_payload": json_payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "request_id": "req-http",
            "status": "completed",
            "content": "HTTP fallback 报告",
            "sources": [
                {
                    "title": "PyPI",
                    "url": "https://pypi.org/project/tavily-python/",
                    "content": "当前版本信息",
                }
            ],
        }

    async def _fake_write_cache(key: str, value: dict[str, object]) -> None:
        del key, value

    monkeypatch.setattr(client, "_call_tavily", _fake_call)
    monkeypatch.setattr(client, "_call_tavily_http", _fake_http)
    monkeypatch.setattr(client, "_write_cache", _fake_write_cache)

    output = await client.research(WebResearchArgs(query="查询 Tavily 版本"))

    assert len(http_calls) == 1
    assert http_calls[0]["method"] == "POST"
    assert http_calls[0]["path"] == "/research"
    assert http_calls[0]["timeout_seconds"] is None
    assert http_calls[0]["json_payload"]["input"] == "查询 Tavily 版本"
    assert "query" not in http_calls[0]["json_payload"]
    assert http_calls[0]["json_payload"]["citation_format"] == "numbered"
    assert output["request_id"] == "req-http"
    assert output["report"] == "HTTP fallback 报告"
    assert output["results"][0]["url"] == "https://pypi.org/project/tavily-python/"


@pytest.mark.asyncio
async def test_web_search_aggregates_tavily_and_searxng_without_timeout_kwargs() -> None:
    tavily_provider = _RecordingSearchProvider("tavily")
    searxng_provider = _RecordingSearchProvider("searxng")
    tool = build_web_search_tool(
        _build_settings(),
        search_providers=[tavily_provider, searxng_provider],
        read_provider=None,
    )

    payload = json.loads(await tool.ainvoke({"query": "测试双 provider 搜索"}))

    assert tavily_provider.calls
    assert searxng_provider.calls
    assert all("timeout_seconds" not in call for call in tavily_provider.calls)
    assert all("timeout_seconds" not in call for call in searxng_provider.calls)
    assert "timeout_seconds" not in payload["parameters"]
    assert {"tavily", "searxng"}.issubset(
        {item["provider"] for item in payload["provider_reports"]}
    )


@pytest.mark.asyncio
async def test_research_registry_uses_aggregated_web_search_without_tavily_research() -> None:
    bundle = await build_research_tool_registry(
        settings=Settings(
            web_search_api_key="tvly-test",
            web_search_cache_enabled=False,
            searxng_search_enabled=True,
            jina_read_enabled=False,
        )
    )

    tool_names = {tool.name for tool in bundle.tools}

    assert "web_search" in tool_names
    assert "tavily_research" not in tool_names
    assert "tavily_search" not in tool_names
    assert "searxng_search" not in tool_names
    assert bundle.tool_groups["web_provider_ids"][:2] == ("tavily", "searxng")
