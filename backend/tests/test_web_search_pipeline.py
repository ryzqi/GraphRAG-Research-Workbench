from langchain_core.documents import Document

from app.search.web.pipeline import WebSearchPipeline


class _StaticRetriever:
    def __init__(self, provider_name: str, mapping: dict[str, list[Document]]) -> None:
        self.provider_name = provider_name
        self._mapping = mapping

    async def aretrieve(
        self,
        query: str,
        *,
        max_results: int,
        **_: object,
    ) -> list[Document]:
        return list(self._mapping.get(query, []))[:max_results]


class _StaticReadProvider:
    provider_name = "jina_reader"

    def __init__(self, payload_by_url: dict[str, dict[str, str]]) -> None:
        self._payload_by_url = payload_by_url

    async def read(self, *, url: str, timeout_seconds: float | None = None) -> dict[str, str | None]:
        payload = self._payload_by_url[url]
        return {
            "url": url,
            "title": payload.get("title", ""),
            "content": payload.get("content", ""),
            "error": None,
        }


def _doc(
    *,
    provider: str,
    rank: int,
    title: str,
    url: str,
    snippet: str,
) -> Document:
    return Document(
        page_content=snippet,
        metadata={
            "provider": provider,
            "provider_rank": rank,
            "title": title,
            "url": url,
            "canonical_url": url,
            "domain": url.split("/")[2],
            "retrieval_query": "langchain mcp docs",
        },
    )


async def test_web_search_pipeline_rewrites_and_fuses_results() -> None:
    pipeline = WebSearchPipeline(
        retrievers=[
            _StaticRetriever(
                "tavily",
                {
                    "langchain mcp docs": [
                        _doc(
                            provider="tavily",
                            rank=1,
                            title="MCP Tools - Docs by LangChain",
                            url="https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools",
                            snippet="short",
                        ),
                    ],
                    "site:docs.langchain.com langchain mcp docs": [
                        _doc(
                            provider="tavily",
                            rank=1,
                            title="MCP - Docs by LangChain",
                            url="https://docs.langchain.com/oss/python/langchain-mcp",
                            snippet="python docs",
                        ),
                    ],
                },
            ),
            _StaticRetriever(
                "searxng",
                {
                    "langchain mcp docs": [
                        _doc(
                            provider="searxng",
                            rank=1,
                            title="MCP Tools - Docs by LangChain",
                            url="https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools",
                            snippet="official docs",
                        ),
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

    output = await pipeline.search(query="langchain mcp docs", max_results=2)

    assert output["query_plan"]["rewritten_queries"] == [
        "langchain mcp docs",
        "site:docs.langchain.com langchain mcp docs",
    ]
    assert output["results"][0]["url"] == "https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools"
    assert output["results"][0]["overlap_count"] == 2
    assert output["results"][0]["source"] == "tavily"
    assert "Quickstart" in output["results"][0]["snippet"]
