"""Web 搜索工具。

支持联网搜索补足最新信息，封装多个搜索后端。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.core.settings import Settings


class WebSearchArgs(BaseModel):
    """Web 搜索参数。"""

    query: str = Field(..., description="搜索查询")
    max_results: int = Field(default=5, ge=1, le=10, description="最大结果数")
    search_type: Literal["general", "news", "academic"] = Field(
        default="general", description="搜索类型"
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
    """Web 搜索客户端，封装多个搜索后端。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._backend = settings.web_search_backend
        self._api_key = settings.web_search_api_key
        self._cache_enabled = getattr(settings, "web_search_cache_enabled", True)
        self._cache_ttl = getattr(settings, "web_search_cache_ttl_seconds", 300)

    def _cache_key(self, query: str, search_type: str, max_results: int) -> str:
        raw = f"{query}:{search_type}:{max_results}"
        return f"web_search:{hashlib.md5(raw.encode()).hexdigest()}"

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_type: str = "general",
    ) -> list[WebSearchResult]:
        """执行搜索。"""
        if self._backend == "tavily":
            return await self._search_tavily(query, max_results, search_type)
        if self._backend == "serp":
            return await self._search_serp(query, max_results, search_type)
        raise ValueError(f"不支持的 WEB_SEARCH_BACKEND={self._backend!r}")

    async def _search_tavily(
        self, query: str, max_results: int, search_type: str
    ) -> list[WebSearchResult]:
        """Tavily 搜索后端。"""
        try:
            from tavily import AsyncTavilyClient
        except ImportError as exc:
            raise RuntimeError(
                "未安装 tavily 依赖，无法使用 WEB_SEARCH_BACKEND=tavily（请安装 tavily 并配置 WEB_SEARCH_API_KEY）"
            ) from exc

        if not self._api_key:
            raise RuntimeError("未配置 WEB_SEARCH_API_KEY，无法使用 web_search")

        client = AsyncTavilyClient(api_key=self._api_key)
        topic = "news" if search_type == "news" else "general"

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

    async def _search_serp(
        self, query: str, max_results: int, search_type: str
    ) -> list[WebSearchResult]:
        """SerpAPI 搜索后端。"""
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "未安装 httpx 依赖，无法使用 WEB_SEARCH_BACKEND=serp（请安装 httpx 并配置 WEB_SEARCH_API_KEY）"
            ) from exc

        if not self._api_key:
            raise RuntimeError("未配置 WEB_SEARCH_API_KEY，无法使用 web_search")

        params = {
            "q": query,
            "api_key": self._api_key,
            "num": max_results,
        }
        if search_type == "news":
            params["tbm"] = "nws"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://serpapi.com/search", params=params
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        items = data.get("organic_results", []) or data.get("news_results", [])
        for item in items[:max_results]:
            results.append(
                WebSearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", "")[:500],
                    source="serp",
                    published_at=item.get("date"),
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
