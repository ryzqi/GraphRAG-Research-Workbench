from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.integrations import embedding_client as embedding_client_module


class _FakeResponse:
    def __init__(
        self,
        payload: dict,
        *,
        status_code: int = 200,
        url: str = "https://embeddings.example/v1/embeddings",
    ) -> None:
        self._payload = payload
        self._status_code = status_code
        self._request = httpx.Request("POST", url)

    def raise_for_status(self) -> None:
        if self._status_code < 400:
            return None
        response = httpx.Response(
            self._status_code,
            request=self._request,
            json=self._payload,
        )
        raise httpx.HTTPStatusError(
            f"bad response status code {self._status_code}",
            request=self._request,
            response=response,
        )

    def json(self) -> dict:
        return self._payload


class _RecordingAsyncClient:
    def __init__(self, responses: list[_FakeResponse | Exception]) -> None:
        self._responses = list(responses)
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
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _settings(
    *,
    embedding_dim: int | None,
    embedding_retry_max_retries: int = 2,
    embedding_retry_base_delay_seconds: float = 0.2,
    embedding_retry_jitter_ratio: float = 0.2,
    embedding_breaker_failure_threshold: int = 2,
    embedding_breaker_open_seconds: float = 30.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        embedding_base_url="https://embeddings.example/v1",
        embedding_api_key="test-key",
        embedding_model="test-embedding-model",
        embedding_timeout_seconds=12.5,
        embedding_dim=embedding_dim,
        embedding_retry_max_retries=embedding_retry_max_retries,
        embedding_retry_base_delay_seconds=embedding_retry_base_delay_seconds,
        embedding_retry_jitter_ratio=embedding_retry_jitter_ratio,
        embedding_breaker_failure_threshold=embedding_breaker_failure_threshold,
        embedding_breaker_open_seconds=embedding_breaker_open_seconds,
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
        responses=[_FakeResponse({"data": [{"embedding": [0.1] * 4096}]})],
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
        responses=[_FakeResponse({"data": [{"embedding": [0.1] * 1024}]})],
    )

    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    with pytest.raises(RuntimeError, match="expected=4096, actual=1024"):
        await client.embed(texts=["hello world"])


@pytest.mark.asyncio
async def test_embed_retries_retryable_502_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_client_module,
        "get_settings",
        lambda: _settings(
            embedding_dim=4,
            embedding_retry_max_retries=2,
            embedding_retry_base_delay_seconds=0.01,
            embedding_retry_jitter_ratio=0.0,
        ),
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(embedding_client_module.asyncio, "sleep", _fake_sleep)
    http_client = _RecordingAsyncClient(
        responses=[
            _FakeResponse({"error": "bad gateway"}, status_code=502),
            _FakeResponse({"error": "bad gateway"}, status_code=502),
            _FakeResponse({"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}),
        ],
    )

    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    embeddings = await client.embed(texts=["hello world"], stage="query_main")

    assert embeddings == [[0.1, 0.2, 0.3, 0.4]]
    assert len(http_client.calls) == 3
    assert sleep_calls == [0.01, 0.02]


@pytest.mark.asyncio
async def test_embed_does_not_retry_non_retryable_4xx_and_exposes_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_client_module,
        "get_settings",
        lambda: _settings(
            embedding_dim=4,
            embedding_retry_max_retries=3,
            embedding_retry_base_delay_seconds=0.01,
            embedding_retry_jitter_ratio=0.0,
        ),
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(embedding_client_module.asyncio, "sleep", _fake_sleep)
    http_client = _RecordingAsyncClient(
        responses=[
            _FakeResponse({"error": "bad request"}, status_code=400),
        ],
    )

    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    with pytest.raises(Exception) as exc_info:
        await client.embed(texts=["hello world"], stage="query_main")

    error = exc_info.value
    assert error.__class__.__name__ == "EmbeddingCallError"
    assert getattr(error, "status_code", None) == 400
    assert getattr(error, "stage", None) == "query_main"
    assert getattr(error, "retryable", None) is False
    assert getattr(error, "attempts", None) == 1
    assert len(http_client.calls) == 1
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_optional_stage_short_circuits_when_breaker_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_client_module,
        "get_settings",
        lambda: _settings(
            embedding_dim=4,
            embedding_retry_max_retries=0,
            embedding_breaker_failure_threshold=2,
            embedding_breaker_open_seconds=30.0,
        ),
    )
    http_client = _RecordingAsyncClient(
        responses=[
            _FakeResponse({"error": "bad gateway"}, status_code=502),
            _FakeResponse({"error": "bad gateway"}, status_code=502),
            _FakeResponse({"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}),
        ],
    )
    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    for _ in range(2):
        with pytest.raises(Exception):
            await client.embed(texts=["cache query"], stage="semantic_cache_lookup")

    with pytest.raises(Exception) as exc_info:
        await client.embed(texts=["cache query"], stage="semantic_cache_lookup")

    error = exc_info.value
    assert error.__class__.__name__ == "EmbeddingCallError"
    assert getattr(error, "stage", None) == "semantic_cache_lookup"
    assert getattr(error, "breaker_state", None) == "open"
    assert getattr(error, "attempts", None) == 0
    assert len(http_client.calls) == 2


@pytest.mark.asyncio
async def test_optional_stage_half_open_probe_success_closes_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(
        embedding_client_module,
        "get_settings",
        lambda: _settings(
            embedding_dim=4,
            embedding_retry_max_retries=0,
            embedding_breaker_failure_threshold=1,
            embedding_breaker_open_seconds=5.0,
        ),
    )
    monkeypatch.setattr(
        embedding_client_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
        raising=False,
    )
    http_client = _RecordingAsyncClient(
        responses=[
            _FakeResponse({"error": "bad gateway"}, status_code=502),
            _FakeResponse({"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}),
            _FakeResponse({"data": [{"embedding": [0.4, 0.3, 0.2, 0.1]}]}),
        ],
    )
    client = embedding_client_module.EmbeddingClient(http_client=http_client)

    with pytest.raises(Exception):
        await client.embed(texts=["cache query"], stage="semantic_cache_lookup")

    with pytest.raises(Exception):
        await client.embed(texts=["cache query"], stage="semantic_cache_lookup")

    clock["now"] = 106.0
    recovered = await client.embed(texts=["cache query"], stage="semantic_cache_lookup")
    healthy = await client.embed(texts=["cache query"], stage="semantic_cache_lookup")

    assert recovered == [[0.1, 0.2, 0.3, 0.4]]
    assert healthy == [[0.4, 0.3, 0.2, 0.1]]
    assert len(http_client.calls) == 3
