from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.retrieval_service import (
    RetrievalLayerDraft,
    RetrievalResult,
    RetrievalService,
    RetrievedChunk,
)


class _FakeSqlResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _FakeDb:
    def __init__(self, *, kb_id: uuid.UUID) -> None:
        self.kb_id = kb_id
        self.updated_at = datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc)

    async def execute(self, stmt) -> _FakeSqlResult:
        sql = str(stmt)
        if "kb_config_snapshots" in sql:
            return _FakeSqlResult([])
        if "knowledge_bases" in sql and "updated_at" in sql:
            return _FakeSqlResult([(self.kb_id, self.updated_at)])
        if "knowledge_bases" in sql and "index_config" in sql:
            return _FakeSqlResult(
                [
                    (
                        self.kb_id,
                        {"chunking": {"general_strategy": "markdown_heading"}},
                    )
                ]
            )
        raise AssertionError(f"unexpected sql: {sql}")


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        del ex
        self.data[key] = value


class _FakeMilvus:
    def __init__(self, *, record: dict[str, object]) -> None:
        self._record = record
        self.query_by_chunk_ids_calls = 0

    async def query_by_chunk_ids(self, *, chunk_ids: list[str]) -> list[dict[str, object]]:
        assert chunk_ids == [str(self._record["chunk_id"])]
        self.query_by_chunk_ids_calls += 1
        return [self._record]


def _chunk(*, kb_id: uuid.UUID, material_id: uuid.UUID, chunk_id: uuid.UUID, score: float) -> RetrievalResult:
    return RetrievalResult(
        chunk=RetrievedChunk(
            id=chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            content=f"chunk-{score}",
            context=None,
            locator={"filename": "cache.md"},
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
            chunk_index=0,
            heading_path="Cache",
            global_chunk_order=0,
        ),
        score=score,
        context_text=f"context-{score}",
    )


def _layer(result: RetrievalResult) -> RetrievalLayerDraft:
    return RetrievalLayerDraft(
        retrieval_candidates=[],
        reranked_candidates=[],
        evidence_items=[],
        results=[result],
        stats={"pre_min_score_candidates": 1, "filtered_count": 0},
    )


@pytest.mark.asyncio
async def test_retrieval_cache_misses_when_kb_content_version_changes() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    fake_db = _FakeDb(kb_id=kb_id)
    fake_redis = _FakeRedis()
    fake_milvus = _FakeMilvus(
        record={
            "chunk_id": str(chunk_id),
            "kb_id": str(kb_id),
            "material_id": str(material_id),
            "content": "cached",
            "context": "cached-context",
            "locator": {"filename": "cache.md"},
            "metadata": None,
            "chunk_role": "default",
            "parent_chunk_id": None,
            "child_seq": None,
            "chunk_index": 0,
            "heading_path": "Cache",
            "global_chunk_order": 0,
        }
    )
    service = RetrievalService(
        db=fake_db,
        milvus=fake_milvus,
        embedding=object(),
        redis=fake_redis,
    )
    service._settings = SimpleNamespace(
        retrieval_default_top_k=4,
        retrieval_max_top_k=4,
        retrieval_cache_enabled=True,
        retrieval_cache_ttl_seconds=300,
        retrieval_min_score=0.2,
        retrieval_raw_min_score=None,
        retrieval_rank_fusion_min_score=None,
        retrieval_rerank_min_score=None,
        retrieval_query_lowercase=False,
        retrieval_hybrid_rrf_k=60,
        retrieval_rerank_model="fake-rerank",
        embedding_model="fake-embedding",
    )
    service._maybe_rewrite_query = AsyncMock(
        return_value=SimpleNamespace(
            query="缓存命中",
            rewritten=False,
            reason="disabled",
            latency_ms=0,
        )
    )
    service._ensure_chunk_citation_labels = AsyncMock(return_value=None)
    service.retrieve_layer = AsyncMock(
        side_effect=[
            _layer(
                _chunk(
                    kb_id=kb_id,
                    material_id=material_id,
                    chunk_id=chunk_id,
                    score=0.91,
                )
            ),
            _layer(
                _chunk(
                    kb_id=kb_id,
                    material_id=material_id,
                    chunk_id=chunk_id,
                    score=0.37,
                )
            ),
        ]
    )

    first = await service.retrieve(query="缓存命中", kb_ids=[kb_id], top_k=1)
    assert first[0].score == pytest.approx(0.91)
    assert service.last_stats is not None
    assert service.last_stats.cache_hit is False

    fake_db.updated_at = datetime(2026, 4, 14, 10, 5, tzinfo=timezone.utc)
    second = await service.retrieve(query="缓存命中", kb_ids=[kb_id], top_k=1)

    assert second[0].score == pytest.approx(0.37)
    assert service.last_stats is not None
    assert service.last_stats.cache_hit is False
    assert service.retrieve_layer.await_count == 2
    assert fake_milvus.query_by_chunk_ids_calls == 0
