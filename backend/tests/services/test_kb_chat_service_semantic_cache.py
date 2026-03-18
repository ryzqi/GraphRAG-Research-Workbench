from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.integrations.embedding_client import EmbeddingCallError, EmbeddingCallStage
from app.models.chat_session import AgentMode
from app.services.kb_chat_service import KbChatService


class _FakeConfig:
    def model_dump(self, *, mode: str = "json") -> dict[str, int]:
        assert mode == "json"
        return {"retrieval_top_k": 5}


class _FakeRedis:
    def __init__(self, *, payload: str | None = None, ttl_value: int = 600) -> None:
        self.payload = payload
        self.ttl_value = ttl_value
        self.get_calls: list[str] = []
        self.ttl_calls: list[str] = []
        self.set_calls: list[dict[str, object]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.payload

    async def ttl(self, key: str) -> int:
        self.ttl_calls.append(key)
        return self.ttl_value

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.set_calls.append({"key": key, "value": value, "ex": ex})
        self.payload = value


class _RecordingEmbeddingClient:
    def __init__(
        self,
        *,
        result: list[list[float]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result if result is not None else [[0.9, 0.1]]
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def embed(
        self,
        *,
        texts: list[str],
        stage: str | None = None,
        policy: object | None = None,
    ) -> list[list[float]]:
        self.calls.append({"texts": texts, "stage": stage, "policy": policy})
        if self.error is not None:
            raise self.error
        return self.result


def _build_service(*, redis: _FakeRedis, embedding: _RecordingEmbeddingClient) -> KbChatService:
    service = object.__new__(KbChatService)
    service._settings = SimpleNamespace(
        kb_chat_semantic_cache_enabled=True,
        kb_chat_semantic_cache_similarity_threshold=0.88,
        kb_chat_semantic_cache_ttl_seconds=900,
        kb_chat_semantic_cache_max_items=8,
    )
    service._redis = redis
    service._embedding = embedding
    service._semantic_kb_version = AsyncMock(return_value="kb-v1")
    return service


def _build_session() -> SimpleNamespace:
    return SimpleNamespace(
        id="session-1",
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )


def _retryable_error(*, stage: EmbeddingCallStage, status_code: int, breaker_state: str) -> EmbeddingCallError:
    return EmbeddingCallError(
        stage=stage,
        status_code=status_code,
        retryable=True,
        attempts=0 if breaker_state == "open" else 1,
        batch_size=1,
        input_chars=11,
        breaker_state=breaker_state,
        short_circuited=breaker_state == "open",
    )


@pytest.mark.asyncio
async def test_semantic_cache_lookup_skips_retryable_embedding_failures_with_lookup_stage() -> None:
    redis = _FakeRedis(
        payload=json.dumps(
            [
                {
                    "question": "cache query",
                    "answer": "cached answer",
                    "embedding": [0.9, 0.1],
                }
            ]
        )
    )
    embedding = _RecordingEmbeddingClient(
        error=_retryable_error(
            stage=EmbeddingCallStage.SEMANTIC_CACHE_LOOKUP,
            status_code=502,
            breaker_state="closed",
        )
    )
    service = _build_service(redis=redis, embedding=embedding)

    result = await service._semantic_cache_lookup(
        session=_build_session(),
        kb_chat_config=_FakeConfig(),
        question="cache query",
    )

    assert result is None
    assert embedding.calls == [
        {
            "texts": ["cache query"],
            "stage": "semantic_cache_lookup",
            "policy": None,
        }
    ]


@pytest.mark.asyncio
async def test_semantic_cache_lookup_swallows_untyped_embedding_runtime_errors() -> None:
    redis = _FakeRedis(
        payload=json.dumps(
            [
                {
                    "question": "cache query",
                    "answer": "cached answer",
                    "embedding": [0.9, 0.1],
                }
            ]
        )
    )
    embedding = _RecordingEmbeddingClient(error=RuntimeError("embedding boom"))
    service = _build_service(redis=redis, embedding=embedding)

    result = await service._semantic_cache_lookup(
        session=_build_session(),
        kb_chat_config=_FakeConfig(),
        question="cache query",
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["\u200e", "\u2066", "\u00ad"])
async def test_semantic_cache_lookup_skips_invisible_only_question_before_embedding(
    question: str,
) -> None:
    redis = _FakeRedis(
        payload=json.dumps(
            [
                {
                    "question": "cache query",
                    "answer": "cached answer",
                    "embedding": [0.9, 0.1],
                }
            ]
        )
    )
    embedding = _RecordingEmbeddingClient()
    service = _build_service(redis=redis, embedding=embedding)

    result = await service._semantic_cache_lookup(
        session=_build_session(),
        kb_chat_config=_FakeConfig(),
        question=question,
    )

    assert result is None
    assert embedding.calls == []


@pytest.mark.asyncio
async def test_write_semantic_cache_entry_skips_breaker_open_embedding_failures_with_write_stage() -> None:
    redis = _FakeRedis()
    embedding = _RecordingEmbeddingClient(
        error=_retryable_error(
            stage=EmbeddingCallStage.SEMANTIC_CACHE_WRITE,
            status_code=None,
            breaker_state="open",
        )
    )
    service = _build_service(redis=redis, embedding=embedding)

    await service._write_semantic_cache_entry(
        session=_build_session(),
        kb_chat_config=_FakeConfig(),
        question="cache query",
        answer="cache answer",
        evidence=[],
        stage_summaries={"answer": {"status": "ok"}},
        metrics={"route_consistency_rate": 100.0},
    )

    assert embedding.calls == [
        {
            "texts": ["cache query"],
            "stage": "semantic_cache_write",
            "policy": None,
        }
    ]
    assert redis.get_calls == []
    assert redis.set_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["\u200e", "\u2066", "\u00ad"])
async def test_write_semantic_cache_entry_skips_invisible_only_question_before_embedding(
    question: str,
) -> None:
    redis = _FakeRedis()
    embedding = _RecordingEmbeddingClient()
    service = _build_service(redis=redis, embedding=embedding)

    await service._write_semantic_cache_entry(
        session=_build_session(),
        kb_chat_config=_FakeConfig(),
        question=question,
        answer="cache answer",
        evidence=[],
        stage_summaries={"answer": {"status": "ok"}},
        metrics={"route_consistency_rate": 100.0},
    )

    assert embedding.calls == []
    assert redis.get_calls == []
    assert redis.set_calls == []
