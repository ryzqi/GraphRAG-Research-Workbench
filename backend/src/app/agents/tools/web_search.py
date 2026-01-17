"""Web 搜索工具。

基于 Tavily 实现联网搜索，补足最新信息。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.core.settings import Settings

if TYPE_CHECKING:
    from tavily import AsyncTavilyClient


class WebSearchArgs(BaseModel):
    """Web 搜索参数。"""

    query: str = Field(..., description="搜索查询")
    max_results: int = Field(default=5, ge=1, le=20, description="最大结果数")
    search_type: Literal["general", "news", "finance", "academic"] = Field(
        default="general", description="搜索类型（general/news/finance/academic，academic 会映射为 general）"
    )


@dataclass
class WebSearchResult:
    """单条搜索结果。"""

    title: str
    url: str
    snippet: str
    source: str
    published_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "published_at": self.published_at,
        }


class WebSearchClient:
    """Web 搜索客户端（Tavily）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.web_search_api_key
        self._cache_enabled = getattr(settings, "web_search_cache_enabled", True)
        self._cache_ttl = getattr(settings, "web_search_cache_ttl_seconds", 300)
        self._client: AsyncTavilyClient | None = None

    def _cache_key(self, query: str, search_type: str, max_results: int) -> str:
        raw = f"{query}:{search_type}:{max_results}"
        return f"web_search:{hashlib.md5(raw.encode()).hexdigest()}"

    def _get_client(self) -> "AsyncTavilyClient":
        try:
            from tavily import AsyncTavilyClient
        except ImportError as exc:
            raise RuntimeError(
                "未安装 tavily-python 依赖，无法使用 Tavily Web 搜索（请安装 tavily-python 并配置 WEB_SEARCH_API_KEY）"
            ) from exc

        if not self._api_key:
            raise RuntimeError("未配置 WEB_SEARCH_API_KEY，无法使用 Tavily Web 搜索")

        if self._client is None:
            self._client = AsyncTavilyClient(self._api_key)
        return self._client

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_type: str = "general",
    ) -> list[WebSearchResult]:
        """执行搜索。"""
        return await self._search_tavily(query, max_results, search_type)

    async def _search_tavily(
        self, query: str, max_results: int, search_type: str
    ) -> list[WebSearchResult]:
        """Tavily 搜索后端。"""
        client = self._get_client()
        if search_type == "news":
            topic = "news"
        elif search_type == "finance":
            topic = "finance"
        else:
            # academic 兼容映射为 general
            topic = "general"

        response = await client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            include_answer=False,
        )

        results = []
        for item in response.get("results", [])[:max_results]:
            results.append(
                WebSearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:500],
                    source="tavily",
                    published_at=item.get("published_date"),
                )
            )
        return results


def build_web_search_tool(settings: Settings) -> BaseTool:
    """构建 Web 搜索工具。"""
    client = WebSearchClient(settings)

    async def _search(
        query: str,
        max_results: int = 5,
        search_type: str = "general",
    ) -> str:
        results = await client.search(query, max_results, search_type)
        output = {
            "query": query,
            "search_type": search_type,
            "total_found": len(results),
            "results": [r.to_dict() for r in results],
        }
        return json.dumps(output, ensure_ascii=False)

    return StructuredTool.from_function(
        name="web_search",
        description="从互联网搜索最新信息，返回相关网页摘要。",
        args_schema=WebSearchArgs,
        coroutine=_search,
    )
