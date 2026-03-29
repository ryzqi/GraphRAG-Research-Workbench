"""普通聊天网页搜索共享契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from langchain_core.documents import Document

SearchProviderName = Literal["tavily", "searxng", "jina_reader"]


@dataclass(slots=True, frozen=True)
class SearchQueryPlan:
    """查询计划。"""

    original_query: str
    rewritten_queries: list[str]


class SearchRetriever(Protocol):
    """统一搜索 retriever 协议。"""

    provider_name: SearchProviderName

    async def aretrieve(
        self,
        query: str,
        *,
        max_results: int,
        **kwargs: Any,
    ) -> list[Document]: ...


class ReadProvider(Protocol):
    """统一正文读取 provider 协议。"""

    provider_name: SearchProviderName

    async def read(
        self,
        *,
        url: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]: ...
