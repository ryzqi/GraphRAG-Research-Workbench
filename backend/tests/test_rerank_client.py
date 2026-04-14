from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.rerank_client import RerankClient


class _FakeRerankResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        documents = list(self._payload["documents"])
        top_n = int(self._payload["top_n"])
        return {
            "results": [
                {
                    "index": index,
                    "relevance_score": float(len(documents) - index),
                }
                for index in range(top_n)
            ]
        }


class _FakeRerankAsyncClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeRerankResponse:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeRerankResponse(json)


def _settings(*, max_documents_per_request: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        retrieval_rerank_base_url="https://proxy.internal/v1",
        retrieval_rerank_api_key="rerank-key",
        retrieval_rerank_model="rerank-model",
        retrieval_rerank_timeout_seconds=5.0,
        retrieval_rerank_max_documents_per_request=max_documents_per_request,
    )


@pytest.mark.asyncio
async def test_rerank_client_trims_documents_to_configured_max() -> None:
    http_client = _FakeRerankAsyncClient()
    client = RerankClient(
        settings=_settings(max_documents_per_request=50),
        http_client=http_client,
    )

    documents = [f"doc-{index}" for index in range(60)]
    results = await client.rerank(query="mysql", documents=documents, top_n=55)

    assert len(results) == 50
    assert len(http_client.calls) == 1
    assert len(http_client.calls[0]["json"]["documents"]) == 50
    assert http_client.calls[0]["json"]["top_n"] == 50


@pytest.mark.asyncio
async def test_rerank_client_keeps_full_documents_when_limit_unset() -> None:
    http_client = _FakeRerankAsyncClient()
    client = RerankClient(
        settings=_settings(max_documents_per_request=None),
        http_client=http_client,
    )

    documents = [f"doc-{index}" for index in range(8)]
    results = await client.rerank(query="mysql", documents=documents, top_n=3)

    assert len(results) == 3
    assert len(http_client.calls) == 1
    assert len(http_client.calls[0]["json"]["documents"]) == 8
    assert http_client.calls[0]["json"]["top_n"] == 3
