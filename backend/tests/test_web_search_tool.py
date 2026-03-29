import json

from app.agents.tools.web_search import build_web_search_tool
from app.agents.tools.web_search_providers.base import (
    NormalizedSearchResult,
    ProviderSearchReport,
    ProviderSearchResponse,
)
from app.core.settings import Settings


class _StaticSearchProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        mapping: dict[str, list[NormalizedSearchResult]],
    ) -> None:
        self.provider_name = provider_name
        self._mapping = mapping

    async def search(self, **kwargs: object) -> ProviderSearchResponse:
        query = str(kwargs.get("query") or "")
        results = list(self._mapping.get(query, []))
        return ProviderSearchResponse(
            provider=self.provider_name,
            results=results,
            report=ProviderSearchReport(
                provider=self.provider_name,
                ok=True,
                result_count=len(results),
                elapsed_ms=12,
                error=None,
            ),
        )


class _StaticReadProvider:
    provider_name = "jina_reader"

    def __init__(self, payload_by_url: dict[str, dict[str, str]]) -> None:
        self._payload_by_url = payload_by_url

    async def read(
        self,
        *,
        url: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, str | None]:
        payload = self._payload_by_url.get(url, {})
        return {
            "url": url,
            "title": payload.get("title", ""),
            "content": payload.get("content", ""),
            "error": None,
        }


async def test_build_web_search_tool_uses_langchain_style_pipeline_output() -> None:
    settings = Settings(
        web_search_api_key="test-key",
        searxng_search_enabled=True,
        jina_read_enabled=True,
    )
    tool = build_web_search_tool(
        settings,
        search_providers=[
            _StaticSearchProvider(
                provider_name="tavily",
                mapping={
                    "langchain mcp docs": [
                        NormalizedSearchResult(
                            title="MCP Tools - Docs by LangChain",
                            url="https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools",
                            snippet="short",
                            source_provider="tavily",
                            score=0.9,
                            domain="docs.langchain.com",
                        )
                    ],
                    "site:docs.langchain.com langchain mcp docs": [
                        NormalizedSearchResult(
                            title="MCP - Docs by LangChain",
                            url="https://docs.langchain.com/oss/python/langchain-mcp",
                            snippet="python docs",
                            source_provider="tavily",
                            score=0.7,
                            domain="docs.langchain.com",
                        )
                    ],
                },
            ),
            _StaticSearchProvider(
                provider_name="searxng",
                mapping={
                    "langchain mcp docs": [
                        NormalizedSearchResult(
                            title="MCP Tools - Docs by LangChain",
                            url="https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools",
                            snippet="official docs",
                            source_provider="searxng",
                            score=0.8,
                            domain="docs.langchain.com",
                        )
                    ]
                },
            ),
        ],
        read_provider=_StaticReadProvider(
            {
                "https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools": {
                    "title": "MCP Tools - Docs by LangChain",
                    "content": "Load additional tools from MCP servers. Quickstart and configuration details.",
                }
            }
        ),
    )

    raw_output = await tool.ainvoke({"query": "langchain mcp docs", "max_results": 2})
    payload = json.loads(raw_output)

    assert payload["query_plan"]["rewritten_queries"] == [
        "langchain mcp docs",
        "site:docs.langchain.com langchain mcp docs",
    ]
    assert payload["results"][0]["url"] == "https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools"
    assert payload["results"][0]["source"] == "tavily"
    assert payload["provider_reports"][0]["provider"] == "tavily"
