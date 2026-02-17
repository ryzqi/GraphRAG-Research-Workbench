import pytest

from app.services.retrieval_service import RetrievalService


@pytest.mark.asyncio
async def test_resolve_query_embedding_uses_mean_for_hyde_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RetrievalService(db=None, milvus=None, embedding=None)  # type: ignore[arg-type]

    vectors = {
        "假设文档A": [1.0, 0.0, 1.0],
        "假设文档B": [0.0, 2.0, 1.0],
    }

    async def _fake_get_query_embedding(query: str, *, timeout_seconds=None):  # type: ignore[no-untyped-def]
        return vectors[query]

    monkeypatch.setattr(service, "_get_query_embedding", _fake_get_query_embedding)

    item = {
        "kind": "hyde",
        "query": "假设文档A",
        "hyde_queries": ["假设文档A", "假设文档B"],
        "hyde_aggregation": "mean_embedding",
    }

    embedding, requested_count, used_count, reason = await service._resolve_query_embedding(  # type: ignore[attr-defined]
        item,
        timeout_seconds=None,
    )

    assert embedding == [0.5, 1.0, 1.0]
    assert requested_count == 2
    assert used_count == 2
    assert reason == "none"
