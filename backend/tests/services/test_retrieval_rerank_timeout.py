import asyncio
import uuid

import pytest

from app.services.retrieval_service import RetrievedChunk, RetrievalResult, RetrievalService


class _TimeoutReranker:
    async def rerank(self, **kwargs):
        raise asyncio.TimeoutError()


def _make_result(score: float) -> RetrievalResult:
    return RetrievalResult(
        chunk=RetrievedChunk(
            id=uuid.uuid4(),
            kb_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            content="example",
            context=None,
            locator=None,
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
        ),
        score=score,
    )


@pytest.mark.asyncio
async def test_maybe_rerank_timeout_degrades_to_original_order(monkeypatch) -> None:
    service = RetrievalService(
        db=None,
        milvus=None,
        embedding=None,
        reranker=_TimeoutReranker(),
    )
    monkeypatch.setattr(service._settings, "retrieval_rerank_enabled", True)
    monkeypatch.setattr(service._settings, "retrieval_rerank_timeout_seconds", 0.5)

    results = [_make_result(0.8), _make_result(0.7)]

    ordered, applied, reason, latency_ms = await service._maybe_rerank(
        "query",
        results,
        top_k=2,
        timeout_seconds=0.2,
        hard_timeout=False,
    )

    assert ordered == results
    assert applied is False
    assert reason == "timeout"
    assert latency_ms is None


@pytest.mark.asyncio
async def test_maybe_rerank_timeout_raises_when_hard_timeout(monkeypatch) -> None:
    service = RetrievalService(
        db=None,
        milvus=None,
        embedding=None,
        reranker=_TimeoutReranker(),
    )
    monkeypatch.setattr(service._settings, "retrieval_rerank_enabled", True)
    monkeypatch.setattr(service._settings, "retrieval_rerank_timeout_seconds", 0.5)

    results = [_make_result(0.8)]

    with pytest.raises(asyncio.TimeoutError):
        await service._maybe_rerank(
            "query",
            results,
            top_k=1,
            timeout_seconds=0.2,
            hard_timeout=True,
        )
