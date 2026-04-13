from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.integrations.milvus_client as milvus_client_module


def _settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        milvus_collection="kb_chunks_v1",
        milvus_host="127.0.0.1",
        milvus_port=19530,
        milvus_text_analyzer="chinese",
        milvus_text_analyzer_filters=[],
    )


class _FakeAsyncMilvusClient:
    def __init__(
        self,
        *,
        has_collection: bool,
        describe_result: dict | None = None,
        describe_error: Exception | None = None,
    ) -> None:
        self._has_collection = has_collection
        self._describe_result = describe_result or {}
        self._describe_error = describe_error
        self.calls: list[tuple[str, str]] = []

    async def has_collection(self, *, collection_name: str) -> bool:
        self.calls.append(("has_collection", collection_name))
        return self._has_collection

    async def describe_collection(self, *, collection_name: str) -> dict:
        self.calls.append(("describe_collection", collection_name))
        if self._describe_error is not None:
            raise self._describe_error
        return self._describe_result


@pytest.mark.asyncio
async def test_ready_check_skips_missing_default_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncMilvusClient(
        has_collection=False,
        describe_error=AssertionError("should not describe missing collection"),
    )

    monkeypatch.setattr(milvus_client_module, "get_settings", _settings_stub)
    monkeypatch.setattr(
        milvus_client_module,
        "AsyncMilvusClient",
        lambda uri: fake_client,
    )

    client = milvus_client_module.MilvusClient()

    await client.ready_check()

    assert fake_client.calls == [("has_collection", "kb_chunks_v1")]


@pytest.mark.asyncio
async def test_ready_check_validates_existing_collection_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncMilvusClient(
        has_collection=True,
        describe_result={
            "schema": {
                "fields": [
                    {"name": "chunk_id"},
                    {"name": "kb_id"},
                    {"name": "material_id"},
                    {"name": "chunk_role"},
                    {"name": "parent_chunk_id"},
                    {"name": "child_seq"},
                    {"name": "content"},
                    {"name": "context"},
                    {"name": "locator"},
                    {"name": "metadata"},
                    {"name": "dense_vector"},
                    {"name": "sparse_vector"},
                ]
            }
        },
    )

    monkeypatch.setattr(milvus_client_module, "get_settings", _settings_stub)
    monkeypatch.setattr(
        milvus_client_module,
        "AsyncMilvusClient",
        lambda uri: fake_client,
    )

    client = milvus_client_module.MilvusClient()

    await client.ready_check()

    assert fake_client.calls == [
        ("has_collection", "kb_chunks_v1"),
        ("describe_collection", "kb_chunks_v1"),
    ]
