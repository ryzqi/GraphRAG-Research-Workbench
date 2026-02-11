from __future__ import annotations

import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services.query_dependent_collections import collection_name_for_window
from app.worker.tasks.ingestion_batches import _write_records_to_milvus


class _FakeMilvusClient:
    def __init__(self) -> None:
        self.ensure_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.upsert_calls: list[dict] = []

    async def ensure_collection(self, *, dim: int, collection_name: str | None = None) -> None:
        self.ensure_calls.append({"dim": dim, "collection_name": collection_name})

    async def delete_by_material(
        self,
        material_id: str,
        *,
        collection_name: str | None = None,
    ) -> None:
        self.delete_calls.append(
            {
                "material_id": material_id,
                "collection_name": collection_name,
            }
        )

    async def upsert_batch(self, *, records: list[dict], collection_name: str | None = None) -> None:
        self.upsert_calls.append(
            {
                "records": records,
                "collection_name": collection_name,
            }
        )


@pytest.mark.asyncio
async def test_write_records_to_milvus_routes_records_to_window_collections() -> None:
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_chunking",
                "query_dependent_chunking": {
                    "windows": [
                        {"chunk_size": 200, "chunk_overlap": 20},
                        {"chunk_size": 400, "chunk_overlap": 40},
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
            "metadata": {"window_size": 200, "window_overlap": 20},
        },
        {
            "chunk_id": "c-2",
            "kb_id": "kb-1",
            "material_id": "m-1",
            "dense_vector": [0.3, 0.4],
            "metadata": {"window_size": 400, "window_overlap": 40},
        },
    ]

    fake_milvus = _FakeMilvusClient()
    await _write_records_to_milvus(
        milvus=fake_milvus,
        index_config=index_config,
        base_collection="kb_chunks_v1",
        material_id="m-1",
        records=records,
        embedding_dim=2,
    )

    expected_collections = [
        collection_name_for_window("kb_chunks_v1", 200, 20),
        collection_name_for_window("kb_chunks_v1", 400, 40),
    ]

    assert [call["collection_name"] for call in fake_milvus.ensure_calls] == expected_collections
    assert [call["collection_name"] for call in fake_milvus.delete_calls] == expected_collections
    assert [call["collection_name"] for call in fake_milvus.upsert_calls] == expected_collections
    assert [len(call["records"]) for call in fake_milvus.upsert_calls] == [1, 1]
