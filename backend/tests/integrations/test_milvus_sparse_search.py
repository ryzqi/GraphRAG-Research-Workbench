from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.milvus_client import MilvusClient


class _FakeAsyncMilvusSearchClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs: object) -> list[list[object]]:
        self.calls.append(dict(kwargs))
        return [
            [
                SimpleNamespace(
                    entity={
                        "chunk_id": "11111111-1111-1111-1111-111111111111",
                        "kb_id": "22222222-2222-2222-2222-222222222222",
                        "material_id": "33333333-3333-3333-3333-333333333333",
                        "chunk_role": "default",
                        "parent_chunk_id": "",
                        "child_seq": 0,
                        "content": "CoT 适合单路径、步骤明确的推理任务。",
                        "context": "CoT 适合单路径、步骤明确的推理任务。",
                        "locator": {"citation_label": "Agent基础"},
                        "metadata": {"source": "test"},
                    },
                    distance=0.88,
                )
            ]
        ]


@pytest.mark.asyncio
async def test_sparse_search_uses_bm25_search_api_and_sparse_vector_field() -> None:
    fake_client = _FakeAsyncMilvusSearchClient()
    client = object.__new__(MilvusClient)
    client._client = fake_client
    client._collection = "kb_chunks_v1"
    client._field_cache = set()

    async def _fake_load_field_cache(*, collection_name: str | None = None) -> None:
        assert collection_name == "kb_chunks_v1"

    client._load_field_cache = _fake_load_field_cache
    client._assert_schema_compatible = lambda: None

    hits = await client.sparse_search(
        query="CoT 适合什么场景？",
        kb_ids=["kb-test"],
        top_k=2,
        extra_filter_expr="tenant == 'demo'",
    )

    assert len(hits) == 1
    assert hits[0].chunk_id == "11111111-1111-1111-1111-111111111111"
    assert hits[0].score == pytest.approx(0.88)

    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["collection_name"] == "kb_chunks_v1"
    assert call["data"] == ["CoT 适合什么场景？"]
    assert call["anns_field"] == "sparse_vector"
    assert call["limit"] == 2
    assert call["search_params"] == {"metric_type": "BM25"}
    assert 'kb_id in ["kb-test"]' in str(call["filter"])
    assert "tenant == 'demo'" in str(call["filter"])
