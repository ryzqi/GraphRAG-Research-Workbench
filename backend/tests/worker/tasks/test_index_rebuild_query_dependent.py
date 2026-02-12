from __future__ import annotations

import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services.query_dependent_collections import collection_name_for_window
from app.worker.tasks.index_rebuild import (
    _prepare_rebuild_collections,
    _upsert_rebuild_records,
)


class _FakeMilvusClient:
    def __init__(self) -> None:
        self.ensure_calls: list[dict] = []
        self.delete_kb_calls: list[dict] = []
        self.upsert_calls: list[dict] = []

    async def ensure_collection(self, *, dim: int, collection_name: str | None = None) -> None:
        self.ensure_calls.append({"dim": dim, "collection_name": collection_name})

    async def delete_by_kb_id(self, kb_id: str, *, collection_name: str | None = None) -> None:
        self.delete_kb_calls.append({"kb_id": kb_id, "collection_name": collection_name})

    async def upsert_batch(self, *, records: list[dict], collection_name: str | None = None) -> None:
        self.upsert_calls.append({"records": records, "collection_name": collection_name})


@pytest.mark.asyncio
async def test_rebuild_routes_cleanup_and_upsert_for_each_multiscale_window() -> None:
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_multiscale",
                "query_dependent_multiscale": {
                    "windows": [
                        {"chunk_size_tokens": 128, "chunk_overlap_tokens": 16},
                        {"chunk_size_tokens": 256, "chunk_overlap_tokens": 32},
                    ]
                },
            }
        }
    )

    records = [
        {
            "chunk_id": "c-1",
            "kb_id": "kb-1",
            "material_id": "m-1",
            "dense_vector": [0.1, 0.2],
            "window_size_tokens": 128,
            "window_overlap_tokens": 16,
            "metadata": {"window_size_tokens": 128, "window_overlap_tokens": 16},
        },
        {
            "chunk_id": "c-2",
            "kb_id": "kb-1",
            "material_id": "m-1",
            "dense_vector": [0.3, 0.4],
            "window_size_tokens": 256,
            "window_overlap_tokens": 32,
            "metadata": {"window_size_tokens": 256, "window_overlap_tokens": 32},
        },
    ]

    fake_milvus = _FakeMilvusClient()

    await _prepare_rebuild_collections(
        milvus_client=fake_milvus,
        index_config=index_config,
        base_collection="kb_chunks_v1",
        kb_id="kb-1",
        embedding_dim=2,
    )

    await _upsert_rebuild_records(
        milvus_client=fake_milvus,
        index_config=index_config,
        base_collection="kb_chunks_v1",
        records=records,
        embedding_dim=2,
    )

    expected_collections = [
        collection_name_for_window("kb_chunks_v1", 128, 16),
        collection_name_for_window("kb_chunks_v1", 256, 32),
    ]

    assert [call["collection_name"] for call in fake_milvus.ensure_calls] == [
        expected_collections[0],
        expected_collections[1],
        expected_collections[0],
        expected_collections[1],
    ]

    assert [call["collection_name"] for call in fake_milvus.delete_kb_calls] == [
        None,
        expected_collections[0],
        expected_collections[1],
    ]

    assert [call["collection_name"] for call in fake_milvus.upsert_calls] == expected_collections
    assert [len(call["records"]) for call in fake_milvus.upsert_calls] == [1, 1]
