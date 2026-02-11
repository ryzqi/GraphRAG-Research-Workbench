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
async def test_rebuild_routes_cleanup_and_upsert_for_each_query_dependent_window() -> None:
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_chunking",
                "query_dependent_chunking": {
                    "windows": [
                        {"chunk_size": 256, "chunk_overlap": 32},
                        {"chunk_size": 512, "chunk_overlap": 64},
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
            "metadata": {"window_size": 256, "window_overlap": 32},
        },
        {
            "chunk_id": "c-2",
            "kb_id": "kb-1",
            "material_id": "m-1",
            "dense_vector": [0.3, 0.4],
            "metadata": {"window_size": 512, "window_overlap": 64},
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
        collection_name_for_window("kb_chunks_v1", 256, 32),
        collection_name_for_window("kb_chunks_v1", 512, 64),
    ]

    assert [call["collection_name"] for call in fake_milvus.delete_kb_calls] == expected_collections
    assert [call["collection_name"] for call in fake_milvus.upsert_calls] == expected_collections
    assert [len(call["records"]) for call in fake_milvus.upsert_calls] == [1, 1]
