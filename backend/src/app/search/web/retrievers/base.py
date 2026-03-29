"""Search provider -> LangChain Document 适配。"""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.documents import Document

from app.agents.tools.web_search_providers.base import ProviderSearchResponse
from app.search.web.documents import build_document


class SearchProviderBackend(Protocol):
    """旧 provider 适配层协议。"""

    provider_name: str

    async def search(self, **kwargs: Any) -> ProviderSearchResponse: ...


def provider_response_to_documents(
    response: ProviderSearchResponse,
    *,
    query: str,
) -> list[Document]:
    documents = []
    for rank, item in enumerate(response.results, start=1):
        documents.append(
            build_document(
                provider=response.provider,
                provider_rank=rank,
                query=query,
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                published_at=item.published_at,
                raw_score=item.score,
            )
        )
    return documents


def format_provider_error(response: ProviderSearchResponse) -> str:
    error = response.report.error
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip()
        detail = str(error.get("detail") or "").strip()
        parts = [part for part in [code, message, detail] if part]
        if parts:
            return " | ".join(parts)
    return f"{response.provider} provider failed"


class ProviderSearchRetriever:
    """把旧 provider.search 结果转成 LangChain Document。"""

    def __init__(self, provider: SearchProviderBackend) -> None:
        self.provider_name = str(provider.provider_name)
        self._provider = provider

    async def aretrieve(
        self,
        query: str,
        *,
        max_results: int,
        **kwargs: Any,
    ) -> list[Document]:
        response = await self._provider.search(
            query=query,
            max_results=max_results,
            **kwargs,
        )
        if not response.report.ok and not response.results:
            raise RuntimeError(format_provider_error(response))
        return provider_response_to_documents(response, query=query)
