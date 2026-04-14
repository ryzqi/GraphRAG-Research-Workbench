from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.embedding_client import EmbeddingClient


class _FakeEmbeddingResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        inputs = list(self._payload["input"])
        dim = int(self._payload.get("dimensions", 3) or 3)
        return {
            "data": [
                {"embedding": [float(index)] * dim}
                for index, _ in enumerate(inputs)
            ]
        }


class _FakeEmbeddingAsyncClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeEmbeddingResponse:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeEmbeddingResponse(json)


def _settings(*, max_batch_size: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        embedding_base_url="https://proxy.internal/v1",
        embedding_api_key="embed-key",
        embedding_model="embed-model",
        embedding_dim=3,
        embedding_timeout_seconds=5.0,
        embedding_retry_max_retries=0,
        embedding_breaker_failure_threshold=3,
        embedding_breaker_open_seconds=30.0,
        embedding_retry_base_delay_seconds=0.0,
        embedding_retry_jitter_ratio=0.0,
        embedding_max_batch_size=max_batch_size,
    )


@pytest.mark.asyncio
async def test_embedding_client_splits_requests_by_configured_max_batch_size() -> None:
    http_client = _FakeEmbeddingAsyncClient()
    client = EmbeddingClient(
        http_client=http_client,
        settings=_settings(max_batch_size=25),
    )

    texts = [f"text-{index}" for index in range(32)]
    embeddings = await client.embed(texts=texts)

    assert len(embeddings) == 32
    assert [len(call["json"]["input"]) for call in http_client.calls] == [25, 7]
    assert all(call["json"]["dimensions"] == 3 for call in http_client.calls)


@pytest.mark.asyncio
async def test_embedding_client_keeps_single_request_when_batch_limit_unset() -> None:
    http_client = _FakeEmbeddingAsyncClient()
    client = EmbeddingClient(
        http_client=http_client,
        settings=_settings(max_batch_size=None),
    )

    embeddings = await client.embed(texts=["alpha", "beta"])

    assert len(embeddings) == 2
    assert len(http_client.calls) == 1
    assert http_client.calls[0]["json"]["input"] == ["alpha", "beta"]
