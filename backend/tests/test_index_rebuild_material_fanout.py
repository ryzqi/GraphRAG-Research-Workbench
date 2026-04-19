from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
import time
import uuid

import pytest

from app.worker.tasks import index_rebuild
from app.services.chunking import ChunkItem


class _SessionContext(AbstractAsyncContextManager):
    def __init__(self, session: SimpleNamespace) -> None:
        self._session = session

    async def __aenter__(self) -> SimpleNamespace:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[SimpleNamespace] = []

    def __call__(self) -> _SessionContext:
        session = SimpleNamespace(tag=f"session_{len(self.sessions)}")
        self.sessions.append(session)
        return _SessionContext(session)


@pytest.mark.asyncio
async def test_process_materials_with_sessions_fans_out_and_uses_distinct_sessions() -> None:
    helper = getattr(index_rebuild, "_process_materials_with_sessions", None)
    assert helper is not None, "missing _process_materials_with_sessions helper"

    session_factory = _SessionFactory()
    materials = [SimpleNamespace(id=index) for index in range(10)]
    state = {"active": 0, "max_active": 0, "session_tags": []}

    async def _processor(material: SimpleNamespace, session: SimpleNamespace) -> int:
        state["session_tags"].append(session.tag)
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return material.id

    started_at = time.perf_counter()
    results = await helper(
        materials=materials,
        sessionmaker=session_factory,
        concurrency=4,
        processor=_processor,
    )
    elapsed = time.perf_counter() - started_at

    assert state["max_active"] == 4
    assert len(set(state["session_tags"])) == len(materials)
    assert results == [material.id for material in materials]
    assert elapsed < 0.3


@pytest.mark.asyncio
async def test_process_index_rebuild_material_stops_before_persist_when_cancelled(
    monkeypatch,
) -> None:
    cancel_event = asyncio.Event()
    state = {"replace_calls": 0, "upsert_calls": 0}

    class _FakeSession:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.rollback_calls = 0

        async def commit(self) -> None:
            self.commit_calls += 1

        async def rollback(self) -> None:
            self.rollback_calls += 1

    class _FakeChunkStore:
        def __init__(self, _session: _FakeSession) -> None:
            return None

        async def replace_material_chunks(self, **_kwargs):
            state["replace_calls"] += 1
            return [uuid.uuid4()]

    class _FakeChunker:
        async def split(self, _parsed, _index_config):
            return [ChunkItem(content="chunk-1")]

    async def _fake_parse_material(*_args, **_kwargs):
        return SimpleNamespace(text="full text")

    async def _fake_generate_contexts_for_chunks(**_kwargs):
        return [
            SimpleNamespace(
                context="ctx",
                status="success",
                error=None,
                attempts=1,
            )
        ]

    async def _fake_embed_inputs_with_concurrency(**_kwargs):
        cancel_event.set()
        return [[1.0]]

    async def _fake_upsert_rebuild_records(**_kwargs):
        state["upsert_calls"] += 1
        return ["kb_default"]

    monkeypatch.setattr(index_rebuild, "ChunkPersistenceService", _FakeChunkStore)
    monkeypatch.setattr(index_rebuild, "parse_material", _fake_parse_material)
    monkeypatch.setattr(
        index_rebuild,
        "generate_contexts_for_chunks",
        _fake_generate_contexts_for_chunks,
    )
    monkeypatch.setattr(
        index_rebuild,
        "embed_inputs_with_concurrency",
        _fake_embed_inputs_with_concurrency,
    )
    monkeypatch.setattr(
        index_rebuild,
        "_upsert_rebuild_records",
        _fake_upsert_rebuild_records,
    )

    session = _FakeSession()
    result = await index_rebuild._process_index_rebuild_material(
        material=SimpleNamespace(id=uuid.uuid4(), kb_id=uuid.uuid4()),
        material_session=session,
        settings=SimpleNamespace(
            ingestion_embedding_batch_size=32,
            embedding_max_batch_size=None,
            ingestion_embedding_fanout_concurrency=4,
        ),
        job_id=str(uuid.uuid4()),
        index_config=SimpleNamespace(
            contextual=SimpleNamespace(enabled=True, max_tokens=64, concurrency=1)
        ),
        http_client=object(),
        storage=object(),
        url_crawler_source=None,
        embedding_client=object(),
        chunker=_FakeChunker(),
        context_service=object(),
        milvus_client=SimpleNamespace(delete_by_chunk_ids=None),
        base_collection="kb_default",
        initial_embedding_dim=None,
        cancel_event=cancel_event,
    )

    assert result.canceled is True
    assert result.error is None
    assert session.commit_calls == 0
    assert session.rollback_calls == 1
    assert state["replace_calls"] == 0
    assert state["upsert_calls"] == 0
