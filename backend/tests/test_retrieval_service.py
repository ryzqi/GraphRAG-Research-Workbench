import uuid
from types import SimpleNamespace

import pytest

from app.core.settings import Settings
from app.services.query_rewrite_service import RewriteResult
from app.services.retrieval_service import RetrievalResult, RetrievalService


class DummyMilvus:
    def __init__(self, hits: list[object] | None = None) -> None:
        self.hits = hits or []
        self.last_method: str | None = None

    async def search(self, *, embedding, kb_ids, top_k):
        self.last_method = "search"
        return list(self.hits)

    async def hybrid_search(
        self,
        *,
        embedding,
        query,
        kb_ids,
        top_k,
        ranker,
        dense_weight,
        sparse_weight,
        rrf_k,
    ):
        self.last_method = "hybrid"
        return list(self.hits)


class DummyEmbedding:
    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


def _build_service(settings: Settings) -> RetrievalService:
    service = RetrievalService(
        db=None,  # type: ignore[arg-type]
        milvus=DummyMilvus(),
        embedding=DummyEmbedding(),
        redis=None,
    )
    service._settings = settings
    return service


def test_normalize_query_lowercase() -> None:
    service = _build_service(Settings(retrieval_query_lowercase=True))
    assert service._normalize_query("  Foo\n Bar  ") == "foo bar"


def test_apply_min_score_filters() -> None:
    service = _build_service(Settings(retrieval_min_score=0.5))
    chunk = SimpleNamespace(text="a", token_count=1)
    results = [
        RetrievalResult(chunk=chunk, score=0.4),
        RetrievalResult(chunk=chunk, score=0.6),
    ]
    filtered, count = service._apply_min_score(results)

    assert count == 1
    assert len(filtered) == 1


def test_cache_key_includes_strategy_fingerprint() -> None:
    kb_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    service_a = _build_service(Settings(retrieval_hybrid_enabled=False))
    service_b = _build_service(Settings(retrieval_hybrid_enabled=True))

    key_a = service_a._cache_key(
        "query",
        [kb_id],
        5,
        service_a._strategy_fingerprint(5),
    )
    key_b = service_b._cache_key(
        "query",
        [kb_id],
        5,
        service_b._strategy_fingerprint(5),
    )

    assert key_a != key_b


class DummyResult:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def scalars(self):
        return self

    def all(self):
        return self._chunks


class DummySession:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    async def execute(self, stmt):
        return DummyResult(self._chunks)


class DummyRewriteService:
    async def rewrite(self, query: str) -> RewriteResult:
        return RewriteResult(
            query="rewritten",
            rewritten=True,
            reason=None,
            latency_ms=1,
        )


class DummyRerankClient:
    async def rerank(self, *, query: str, documents: list[str], top_n: int, timeout_seconds: float):
        return [
            SimpleNamespace(index=1, score=0.9),
            SimpleNamespace(index=0, score=0.8),
        ]


@pytest.mark.asyncio
async def test_retrieve_uses_hybrid_when_enabled() -> None:
    chunk_id = uuid.uuid4()
    chunk = SimpleNamespace(
        id=chunk_id,
        kb_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        text="chunk",
        locator={},
        token_count=1,
    )
    hit = SimpleNamespace(chunk_id=str(chunk_id), score=0.9)

    session = DummySession([chunk])
    milvus = DummyMilvus([hit])
    service = RetrievalService(session, milvus, DummyEmbedding(), redis=None)
    service._settings = Settings(
        retrieval_hybrid_enabled=True,
        retrieval_query_rewrite_enabled=False,
        retrieval_rerank_enabled=False,
    )

    results = await service.retrieve(query="test", kb_ids=[chunk.kb_id], top_k=1)

    assert milvus.last_method == "hybrid"
    assert len(results) == 1


@pytest.mark.asyncio
async def test_retrieve_applies_rerank_order() -> None:
    chunk_id1 = uuid.uuid4()
    chunk_id2 = uuid.uuid4()
    chunk1 = SimpleNamespace(
        id=chunk_id1,
        kb_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        text="chunk1",
        locator={},
        token_count=1,
    )
    chunk2 = SimpleNamespace(
        id=chunk_id2,
        kb_id=chunk1.kb_id,
        material_id=uuid.uuid4(),
        text="chunk2",
        locator={},
        token_count=1,
    )
    hits = [
        SimpleNamespace(chunk_id=str(chunk_id1), score=0.9),
        SimpleNamespace(chunk_id=str(chunk_id2), score=0.8),
    ]

    session = DummySession([chunk1, chunk2])
    milvus = DummyMilvus(hits)
    service = RetrievalService(
        session,
        milvus,
        DummyEmbedding(),
        redis=None,
        reranker=DummyRerankClient(),
    )
    service._settings = Settings(
        retrieval_rerank_enabled=True,
        retrieval_query_rewrite_enabled=False,
        retrieval_hybrid_enabled=False,
    )

    results = await service.retrieve(query="test", kb_ids=[chunk1.kb_id], top_k=2)

    assert [r.chunk.id for r in results[:2]] == [chunk_id2, chunk_id1]


@pytest.mark.asyncio
async def test_retrieve_uses_rewrite_result() -> None:
    chunk_id = uuid.uuid4()
    chunk = SimpleNamespace(
        id=chunk_id,
        kb_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        text="chunk",
        locator={},
        token_count=1,
    )
    hit = SimpleNamespace(chunk_id=str(chunk_id), score=0.9)

    session = DummySession([chunk])
    milvus = DummyMilvus([hit])
    service = RetrievalService(
        session,
        milvus,
        DummyEmbedding(),
        redis=None,
        query_rewriter=DummyRewriteService(),
    )
    service._settings = Settings(
        retrieval_query_rewrite_enabled=True,
        retrieval_rerank_enabled=False,
        retrieval_hybrid_enabled=False,
    )

    await service.retrieve(query="test", kb_ids=[chunk.kb_id], top_k=1)

    assert service.last_stats is not None
    assert service.last_stats.effective_query == "rewritten"
