from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.integrations.embedding_client import (
    EmbeddingCallError,
    EmbeddingCallStage,
    EmbeddingClient,
)


class _QueuedHttpClient:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.calls.append(
            {
                "url": url,
                "json": dict(json),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        if not self._outcomes:
            raise AssertionError("unexpected embedding POST call")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, httpx.Response)
        return outcome


def _build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding_base_url="https://embedding.example.test/v1",
        embedding_api_key="test-key",
        embedding_model="text-embedding-3-small",
        embedding_dim=3,
        embedding_timeout_seconds=1.5,
        embedding_retry_max_retries=0,
        embedding_breaker_failure_threshold=1,
        embedding_breaker_open_seconds=60.0,
        embedding_retry_base_delay_seconds=0.0,
        embedding_retry_jitter_ratio=0.0,
    )


def _build_client(http_client: _QueuedHttpClient | None = None) -> EmbeddingClient:
    return EmbeddingClient(
        http_client=http_client,
        settings=_build_settings(),
    )


def _success_response(vector: list[float] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://embedding.example.test/v1/embeddings"),
        json={"data": [{"embedding": vector or [0.11, 0.22, 0.33]}]},
    )


def _connect_timeout() -> httpx.ConnectTimeout:
    return httpx.ConnectTimeout(
        "embedding timeout",
        request=httpx.Request("POST", "https://embedding.example.test/v1/embeddings"),
    )


def test_semantic_cache_stages_use_dedicated_breaker_buckets() -> None:
    client = _build_client()

    lookup_policy = client._policy_for_stage(
        stage=EmbeddingCallStage.SEMANTIC_CACHE_LOOKUP,
        timeout_seconds=None,
        policy=None,
    )
    write_policy = client._policy_for_stage(
        stage=EmbeddingCallStage.SEMANTIC_CACHE_WRITE,
        timeout_seconds=None,
        policy=None,
    )
    hyde_policy = client._policy_for_stage(
        stage=EmbeddingCallStage.HYDE,
        timeout_seconds=None,
        policy=None,
    )
    dedupe_policy = client._policy_for_stage(
        stage=EmbeddingCallStage.DEDUPE,
        timeout_seconds=None,
        policy=None,
    )
    diversity_policy = client._policy_for_stage(
        stage=EmbeddingCallStage.DIVERSITY,
        timeout_seconds=None,
        policy=None,
    )

    assert lookup_policy.breaker_bucket == "semantic_cache_lookup"
    assert write_policy.breaker_bucket == "semantic_cache_write"
    assert lookup_policy.allow_short_circuit_when_open is True
    assert write_policy.allow_short_circuit_when_open is True

    assert hyde_policy.breaker_bucket == "online_optional"
    assert dedupe_policy.breaker_bucket == "online_optional"
    assert diversity_policy.breaker_bucket == "online_optional"
    assert hyde_policy.allow_short_circuit_when_open is True


@pytest.mark.asyncio
async def test_hyde_open_breaker_does_not_short_circuit_semantic_cache_lookup() -> None:
    http_client = _QueuedHttpClient(
        outcomes=[
            _connect_timeout(),
            _success_response([0.44, 0.55, 0.66]),
        ]
    )
    client = _build_client(http_client=http_client)

    with pytest.raises(EmbeddingCallError) as exc_info:
        await client.embed(
            texts=["hyde query"],
            stage=EmbeddingCallStage.HYDE,
        )

    assert exc_info.value.stage == EmbeddingCallStage.HYDE
    assert exc_info.value.breaker_state == "open"

    embeddings = await client.embed(
        texts=["semantic cache lookup query"],
        stage=EmbeddingCallStage.SEMANTIC_CACHE_LOOKUP,
    )

    assert embeddings == [[0.44, 0.55, 0.66]]
    assert [call["json"]["input"][0] for call in http_client.calls] == [
        "hyde query",
        "semantic cache lookup query",
    ]
