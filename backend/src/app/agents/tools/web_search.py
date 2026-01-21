"""Web 搜索工具。

基于 Tavily 实现联网搜索，补足最新信息。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

import httpx
from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, Field

from app.core.settings import Settings

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


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _format_web_search_error(exc: Exception) -> dict:
    status_code = _extract_status_code(exc)
    code = "WEB_SEARCH_UPSTREAM_ERROR"
    message = "Web 搜索暂时不可用，请稍后重试"
    retryable = False

    if isinstance(exc, UsageLimitExceededError):
        code = "WEB_SEARCH_RATE_LIMITED"
        message = "Web 搜索额度不足或请求过于频繁"
        retryable = True
    elif isinstance(exc, InvalidAPIKeyError):
        code = "WEB_SEARCH_AUTH_ERROR"
        message = "WEB_SEARCH_API_KEY 无效或已过期"
    elif isinstance(exc, ForbiddenError):
        code = "WEB_SEARCH_FORBIDDEN"
        message = "Web 搜索被拒绝访问"
    elif isinstance(exc, BadRequestError):
        code = "WEB_SEARCH_BAD_REQUEST"
        message = "Web 搜索请求参数错误"
    elif isinstance(exc, TavilyTimeoutError) or isinstance(exc, httpx.TimeoutException):
        code = "WEB_SEARCH_TIMEOUT"
        message = "Web 搜索超时，请稍后重试"
        retryable = True
    elif status_code == 402:
        code = "WEB_SEARCH_PAYMENT_REQUIRED"
        message = "Tavily 返回 402 Payment Required，可能是余额不足或套餐到期"
    elif status_code == 429:
        code = "WEB_SEARCH_RATE_LIMITED"
        message = "Web 搜索请求过于频繁，请稍后重试"
        retryable = True
    elif status_code in {401, 403}:
        code = "WEB_SEARCH_AUTH_ERROR"
        message = "Web 搜索鉴权失败，请检查 WEB_SEARCH_API_KEY"

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
        try:
            results = await client.search(query, max_results, search_type)
        except Exception as exc:
            error = _format_web_search_error(exc)
            logger.warning(
                "Web 搜索失败",
                extra={
                    "error_code": error.get("code"),
                    "status_code": error.get("status_code"),
                    "search_type": search_type,
                },
                exc_info=exc,
            )
            output = {
                "query": query,
                "search_type": search_type,
                "total_found": 0,
                "results": [],
                "error": error,
            }
            return json.dumps(output, ensure_ascii=False)
        output = {
            "query": query,
            "search_type": search_type,
            "total_found": len(results),
            "results": [r.to_dict() for r in results],
        }
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "web_search",
        description="从互联网搜索最新信息，返回相关网页摘要。",
        args_schema=WebSearchArgs,
    )(_search)
