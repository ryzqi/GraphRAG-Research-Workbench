from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations import embedding_client as embedding_client_module


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _RecordingAsyncClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    async def post(
        self,
        url: str,
        *,
        json: dict,
        headers: dict,
        timeout: float,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse(self._payload)


def _settings(*, embedding_dim: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        embedding_base_url="https://embeddings.example/v1",
        embedding_api_key="test-key",
        embedding_model="test-embedding-model",
        embedding_timeout_seconds=12.5,
        embedding_dim=embedding_dim,
    )


@pytest.mark.asyncio
async def test_embed_includes_configured_dimensions_in_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_client_module,
        "get_settings",
        lambda: _settings(embedding_dim=4096),
    )
    http_client = _RecordingAsyncClient(
        payload={"data": [{"embedding": [0.1] * 4096}]},
    )

    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    embeddings = await client.embed(texts=["hello world"])

    assert len(embeddings[0]) == 4096
    assert http_client.calls == [
        {
            "url": "https://embeddings.example/v1/embeddings",
            "json": {
                "model": "test-embedding-model",
                "input": ["hello world"],
                "dimensions": 4096,
            },
            "headers": {"Authorization": "Bearer test-key"},
            "timeout": 12.5,
        }
    ]


@pytest.mark.asyncio
async def test_embed_raises_when_provider_dimension_mismatches_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_client_module,
        "get_settings",
        lambda: _settings(embedding_dim=4096),
    )
    http_client = _RecordingAsyncClient(
        payload={"data": [{"embedding": [0.1] * 1024}]},
    )

    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    with pytest.raises(RuntimeError, match="expected=4096, actual=1024"):
        await client.embed(texts=["hello world"])
