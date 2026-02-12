from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.milvus_client import MilvusClient


_REQUIRED_FIELDS = {
    'chunk_id',
    'kb_id',
    'material_id',
    'chunk_role',
    'parent_chunk_id',
    'child_seq',
    'content',
    'context',
    'locator',
    'metadata',
    'dense_vector',
    'sparse_vector',
}


class _FakeAsyncMilvusClient:
    def __init__(self) -> None:
        self.has_collection_calls: list[dict] = []
        self.search_calls: list[dict] = []
        self.upsert_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    async def has_collection(self, **kwargs: object) -> bool:
        self.has_collection_calls.append(dict(kwargs))
        return True

    async def create_collection(self, **kwargs: object) -> None:
        raise AssertionError(f'create_collection should not be called: {kwargs}')

    async def search(self, **kwargs: object) -> list[list[object]]:
        self.search_calls.append(dict(kwargs))
        return [[]]

    async def upsert(self, **kwargs: object) -> None:
        self.upsert_calls.append(dict(kwargs))

    async def delete(self, **kwargs: object) -> None:
        self.delete_calls.append(dict(kwargs))


def _build_client(fake_client: _FakeAsyncMilvusClient) -> MilvusClient:
    client = object.__new__(MilvusClient)
    client._client = fake_client
    client._collection = 'kb_chunks_default'
    client._field_cache = set(_REQUIRED_FIELDS)
    client._settings = SimpleNamespace(
        milvus_text_analyzer='standard',
        milvus_text_analyzer_filters=[],
    )
    return client


@pytest.mark.asyncio
async def test_ensure_collection_uses_override_collection_name() -> None:
    fake_client = _FakeAsyncMilvusClient()
    client = _build_client(fake_client)

    await client.ensure_collection(
        dim=768,
        collection_name='kb_chunks_default__msqdc_t100_o20',
    )

    assert fake_client.has_collection_calls == [
        {'collection_name': 'kb_chunks_default__msqdc_t100_o20'}
    ]


@pytest.mark.asyncio
async def test_upsert_batch_passes_collection_override() -> None:
    fake_client = _FakeAsyncMilvusClient()
    client = _build_client(fake_client)

    await client.upsert_batch(
        records=[
            {
                'chunk_id': 'chunk-1',
                'kb_id': 'kb-1',
                'material_id': 'material-1',
                'dense_vector': [0.1, 0.2],
                'metadata': {'window_size_tokens': 100, 'window_overlap_tokens': 20},
            }
        ],
        collection_name='kb_chunks_default__msqdc_t100_o20',
    )

    assert fake_client.upsert_calls[0]['collection_name'] == 'kb_chunks_default__msqdc_t100_o20'


@pytest.mark.asyncio
async def test_search_passes_collection_override() -> None:
    fake_client = _FakeAsyncMilvusClient()
    client = _build_client(fake_client)

    await client.search(
        embedding=[0.1, 0.2],
        kb_ids=[],
        top_k=3,
        collection_name='kb_chunks_default__msqdc_t100_o20',
    )

    assert fake_client.search_calls[0]['collection_name'] == 'kb_chunks_default__msqdc_t100_o20'


@pytest.mark.asyncio
async def test_delete_by_material_passes_collection_override() -> None:
    fake_client = _FakeAsyncMilvusClient()
    client = _build_client(fake_client)

    await client.delete_by_material(
        'material-1',
        collection_name='kb_chunks_default__msqdc_t100_o20',
    )

    assert fake_client.delete_calls[0]['collection_name'] == 'kb_chunks_default__msqdc_t100_o20'
    assert fake_client.delete_calls[0]['filter'] == 'material_id == "material-1"'
