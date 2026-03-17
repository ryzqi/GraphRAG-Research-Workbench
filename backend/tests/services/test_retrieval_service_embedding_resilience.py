from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.integrations.embedding_client import EmbeddingCallError, EmbeddingCallStage
from app.services import retrieval_service as retrieval_service_module


class _FakeEmbedding:
    def __init__(self, handler=None) -> None:
        self._handler = handler or self._default_handler
        self.calls: list[dict[str, object]] = []

    @staticmethod
    def _default_handler(stage: str, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    async def embed(
        self,
        *,
        texts: list[str],
        timeout_seconds: float | None = None,
        stage: str | None = None,
        policy=None,
    ) -> list[list[float]]:
        del policy
        stage_value = str(stage or "default")
        self.calls.append(
            {
                "texts": list(texts),
                "timeout_seconds": timeout_seconds,
                "stage": stage_value,
            }
        )
        return self._handler(stage_value, texts)


class _FakeMilvus:
    def __init__(self, *, hybrid_hits=None) -> None:
        self._hybrid_hits = list(hybrid_hits or [])
        self.hybrid_calls: list[dict[str, object]] = []

    async def hybrid_search(self, **kwargs):
        self.hybrid_calls.append(dict(kwargs))
        return list(self._hybrid_hits)

    async def search(self, **kwargs):
        raise AssertionError(f"unexpected dense search fallback: {kwargs}")

    async def bm25_search(self, **kwargs):
        raise AssertionError(f"unexpected bm25 search fallback: {kwargs}")


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding_timeout_seconds=12.5,
        retrieval_cache_enabled=False,
        retrieval_cache_ttl_seconds=60,
        retrieval_query_lowercase=False,
        retrieval_max_top_k=8,
        retrieval_default_top_k=4,
        retrieval_hybrid_rrf_k=60,
        retrieval_min_score=0.0,
        retrieval_raw_min_score=0.0,
        retrieval_rank_fusion_min_score=0.0,
        retrieval_rerank_min_score=0.0,
        retrieval_rerank_model="test-rerank-model",
        embedding_model="test-embedding-model",
        milvus_collection="kb_chunks",
    )


def _make_hit(
    *,
    kb_id: uuid.UUID,
    material_id: uuid.UUID,
    chunk_id: uuid.UUID,
    content: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        kb_id=str(kb_id),
        material_id=str(material_id),
        chunk_id=str(chunk_id),
        content=content,
        context=None,
        locator={"page": 1},
        metadata={"title": content},
        chunk_role=None,
        parent_chunk_id=None,
        child_seq=None,
    )


def _make_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    embedding: _FakeEmbedding,
    milvus: _FakeMilvus,
) -> retrieval_service_module.RetrievalService:
    monkeypatch.setattr(retrieval_service_module, "get_settings", _settings)
    service = retrieval_service_module.RetrievalService(
        db=SimpleNamespace(),
        milvus=milvus,
        embedding=embedding,
        redis=None,
        query_rewriter=None,
        reranker=None,
    )
    monkeypatch.setattr(
        service,
        "_resolve_feature_flags",
        lambda _overrides: retrieval_service_module.RetrievalFeatureFlags(
            query_rewrite_enabled=False,
            hybrid_enabled=True,
            rerank_enabled=False,
        ),
    )
    monkeypatch.setattr(service, "_load_kb_index_configs", AsyncMock(return_value={}))
    monkeypatch.setattr(
        service, "_hydrate_chunks_from_postgres", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        service,
        "_apply_parent_child_strategy",
        AsyncMock(side_effect=lambda results, *args, **kwargs: results),
    )
    monkeypatch.setattr(
        service,
        "_apply_query_dependent_multiscale_strategy",
        AsyncMock(side_effect=lambda results, *args, **kwargs: results),
    )
    monkeypatch.setattr(
        service,
        "_ensure_chunk_citation_labels",
        AsyncMock(return_value=None),
    )
    return service


@pytest.mark.asyncio
async def test_retrieve_layer_skips_query_when_required_hybrid_embedding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()

    def _handler(stage: str, texts: list[str]) -> list[list[float]]:
        if stage == "query_main":
            raise EmbeddingCallError(
                stage=EmbeddingCallStage.QUERY_MAIN,
                status_code=502,
                retryable=True,
                attempts=2,
                batch_size=len(texts),
                input_chars=sum(len(text) for text in texts),
                breaker_state="open",
            )
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    embedding = _FakeEmbedding(handler=_handler)
    milvus = _FakeMilvus()
    service = _make_service(monkeypatch, embedding=embedding, milvus=milvus)

    layer = await service.retrieve_layer(
        query_items=[
            {
                "kind": "main",
                "query": "what happened?",
                "use_dense": True,
                "use_bm25": True,
            }
        ],
        kb_ids=[kb_id],
        top_n=1,
        per_query_top_k=1,
        global_candidates_limit=2,
        rerank_input_limit=1,
    )

    assert layer.results == []
    assert layer.stats["hybrid_hits"] == 0
    assert layer.stats["rrf_candidates"] == 0
    assert "dense_disabled" not in layer.stats
    assert "diversity_reason" not in layer.stats
    assert milvus.hybrid_calls == []
    assert embedding.calls[0]["stage"] == "query_main"


@pytest.mark.asyncio
async def test_resolve_query_embedding_uses_hyde_stage_for_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vectors_by_text = {
        "hypothesis one": [1.0, 0.0],
        "hypothesis two": [0.0, 1.0],
    }

    def _handler(stage: str, texts: list[str]) -> list[list[float]]:
        assert stage == "hyde"
        return [vectors_by_text[texts[0]]]

    service = _make_service(
        monkeypatch,
        embedding=_FakeEmbedding(handler=_handler),
        milvus=_FakeMilvus(),
    )

    vector, requested, used, reason = await service._resolve_query_embedding(
        {
            "kind": "hyde",
            "query": "main query",
            "hyde_queries": ["hypothesis one", "hypothesis two"],
        }
    )

    assert vector == [0.5, 0.5]
    assert requested == 2
    assert used == 2
    assert reason == "none"
    assert [call["stage"] for call in service._embedding.calls] == ["hyde", "hyde"]


@pytest.mark.asyncio
async def test_retrieve_layer_uses_milvus_native_hybrid_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    embedding = _FakeEmbedding()
    milvus = _FakeMilvus(
        hybrid_hits=[
            _make_hit(
                kb_id=kb_id,
                material_id=material_id,
                chunk_id=chunk_id,
                content="hybrid chunk",
            )
        ]
    )
    service = _make_service(monkeypatch, embedding=embedding, milvus=milvus)

    layer = await service.retrieve_layer(
        query_items=[
            {
                "kind": "main",
                "query": "hybrid only",
                "use_dense": True,
                "use_bm25": True,
            }
        ],
        kb_ids=[kb_id],
        top_n=1,
        per_query_top_k=1,
        global_candidates_limit=2,
        rerank_input_limit=1,
    )

    assert [result.chunk.id for result in layer.results] == [chunk_id]
    assert layer.stats["hybrid_hits"] == 1
    assert layer.stats["rrf_candidates"] == 1
    assert len(milvus.hybrid_calls) == 1
    hybrid_call = milvus.hybrid_calls[0]
    assert hybrid_call["query"] == "hybrid only"
    assert hybrid_call["top_k"] == 1
    assert hybrid_call["rrf_k"] == 60
    assert embedding.calls[0]["stage"] == "query_main"


@pytest.mark.asyncio
async def test_optional_embedding_short_circuit_keeps_candidates_and_exposes_dedupe_reason_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    first_chunk_id = uuid.uuid4()
    second_chunk_id = uuid.uuid4()

    def _handler(stage: str, texts: list[str]) -> list[list[float]]:
        if stage == "dedupe":
            raise EmbeddingCallError(
                stage=EmbeddingCallStage.DEDUPE,
                status_code=None,
                retryable=True,
                attempts=0,
                batch_size=len(texts),
                input_chars=sum(len(text) for text in texts),
                breaker_state="open",
                short_circuited=True,
            )
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    embedding = _FakeEmbedding(handler=_handler)
    milvus = _FakeMilvus(
        hybrid_hits=[
            _make_hit(
                kb_id=kb_id,
                material_id=material_id,
                chunk_id=first_chunk_id,
                content="first chunk",
            ),
            _make_hit(
                kb_id=kb_id,
                material_id=material_id,
                chunk_id=second_chunk_id,
                content="second chunk",
            ),
        ]
    )
    service = _make_service(monkeypatch, embedding=embedding, milvus=milvus)

    layer = await service.retrieve_layer(
        query_items=[
            {
                "kind": "main",
                "query": "hybrid only",
                "use_dense": True,
                "use_bm25": True,
            }
        ],
        kb_ids=[kb_id],
        top_n=2,
        per_query_top_k=2,
        global_candidates_limit=4,
        rerank_input_limit=2,
    )

    assert [result.chunk.id for result in layer.results] == [
        first_chunk_id,
        second_chunk_id,
    ]
    assert layer.stats["dedup_similarity_reason"] == "dedupe:breaker_open"
    assert "diversity_reason" not in layer.stats
    assert layer.stats["optional_embedding_skips"] == ["dedupe:breaker_open"]
    assert [call["stage"] for call in embedding.calls] == ["query_main", "dedupe"]
