from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.integrations.milvus_client import MilvusClient


class _FakeCreateCollectionClient:
    def __init__(self, *, create_error: Exception | None = None) -> None:
        self._create_error = create_error
        self.create_calls: list[dict] = []
        self.has_collection_calls: list[dict] = []

    async def has_collection(self, **kwargs: object) -> bool:
        self.has_collection_calls.append(dict(kwargs))
        return False

    async def create_collection(self, **kwargs: object) -> None:
        self.create_calls.append(dict(kwargs))
        if self._create_error is not None:
            raise self._create_error


def _build_client(
    fake_client: _FakeCreateCollectionClient,
    *,
    analyzer: str = 'standard',
    filters: list[str] | None = None,
) -> MilvusClient:
    client = object.__new__(MilvusClient)
    client._client = fake_client
    client._collection = 'kb_chunks_default'
    client._field_cache = None
    client._settings = SimpleNamespace(
        milvus_text_analyzer=analyzer,
        milvus_text_analyzer_filters=list(filters or []),
    )
    return client


def _extract_content_params(schema: object) -> dict:
    schema_dict = schema.to_dict()
    content_field = next(
        field for field in schema_dict['fields'] if field.get('name') == 'content'
    )
    return dict(content_field.get('params') or {})


@pytest.mark.asyncio
async def test_ensure_collection_sets_enable_analyzer_for_bm25_input_field() -> None:
    fake_client = _FakeCreateCollectionClient()
    client = _build_client(fake_client, analyzer='chinese', filters=['lowercase'])

    await client.ensure_collection(
        dim=768,
        collection_name='kb_chunks_default__msqdc_t100_o20',
    )

    schema = fake_client.create_calls[0]['schema']
    params = _extract_content_params(schema)

    assert params['enable_analyzer'] is True
    assert json.loads(params['analyzer_params']) == {
        'type': 'chinese',
        'filter': ['lowercase'],
    }


@pytest.mark.asyncio
async def test_ensure_collection_error_contains_collection_context() -> None:
    fake_client = _FakeCreateCollectionClient(
        create_error=RuntimeError(
            'BM25 function input field must set enable_analyzer to true'
        )
    )
    client = _build_client(fake_client)

    with pytest.raises(RuntimeError) as exc_info:
        await client.ensure_collection(
            dim=768,
            collection_name='kb_chunks_default__msqdc_t100_o20',
        )

    message = str(exc_info.value)
    assert 'collection=kb_chunks_default__msqdc_t100_o20' in message
    assert 'enable_analyzer=True' in message
    assert '清空并重建 collection' in message
