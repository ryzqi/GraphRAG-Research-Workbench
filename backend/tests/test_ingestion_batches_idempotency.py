from __future__ import annotations

from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace
import uuid

import pytest

from app.core.settings import Settings
from app.models.ingestion_batch import IngestionDocStatus
from app.schemas.knowledge_bases import ChunkingStrategy
from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking import ChunkItem
from app.worker.tasks import ingestion_batches


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class _FakeDbSession:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []
        self.flush_calls = 0

    async def execute(self, statement, params=None):  # noqa: ANN001
        if params is None:
            self.operations.append(("statement", statement))
        else:
            copied_rows = [dict(row) for row in params]
            self.operations.append(("rows", copied_rows))
        return None

    async def flush(self) -> None:
        self.flush_calls += 1


class _SessionContext(AbstractAsyncContextManager):
    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    async def __aenter__(self):  # noqa: ANN201
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _SnapshotResult:
    def scalar_one_or_none(self):  # noqa: ANN201
        return None


class _FakeProcessingSession:
    def __init__(self, state: dict[str, object]) -> None:
        self._state = state
        self.commit_calls = 0
        self.rollback_calls = 0

    async def get(self, model, identity):  # noqa: ANN001, ANN201
        if model is ingestion_batches.SourceMaterial:
            material = self._state["material"]
            if getattr(material, "id", None) == identity:
                return material
            return None
        if model is ingestion_batches.KnowledgeBase:
            kb = self._state["kb"]
            if getattr(kb, "id", None) == identity:
                return kb
            return None
        return None

    async def execute(self, _statement):  # noqa: ANN001, ANN201
        return _SnapshotResult()

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _FakeSessionmaker:
    def __init__(self, state: dict[str, object]) -> None:
        self._state = state
        self.sessions: list[_FakeProcessingSession] = []

    def __call__(self) -> _SessionContext:
        session = _FakeProcessingSession(self._state)
        self.sessions.append(session)
        return _SessionContext(session)


class _FakeMilvus:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.delete_calls = 0
        self.upsert_calls = 0
        self.records_by_material: dict[tuple[str | None, str], list[dict]] = {}

    async def ensure_collection(self, **_kwargs) -> None:
        self.ensure_calls += 1

    async def delete_by_material(
        self,
        material_id: str,
        collection_name: str | None = None,
    ) -> None:
        self.delete_calls += 1
        self.records_by_material[(collection_name, material_id)] = []

    async def upsert_batch(
        self,
        *,
        records: list[dict],
        collection_name: str | None = None,
    ) -> None:
        self.upsert_calls += 1
        material_id = str(records[0]["material_id"]) if records else ""
        self.records_by_material[(collection_name, material_id)] = [dict(item) for item in records]


@pytest.mark.asyncio
async def test_replace_material_chunks_is_idempotent() -> None:
    db = _FakeDbSession()
    service = ChunkPersistenceService(db)
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    chunk_items = [
        ChunkItem(
            content="chunk-1",
            locator={"page_start": 1, "page_end": 1},
            metadata={"token_start": 0, "token_end": 3},
        )
    ]

    first = await service.replace_material_chunks(
        kb_id=kb_id,
        material_id=material_id,
        chunk_items=chunk_items,
        chunk_ids=[chunk_id],
    )
    second = await service.replace_material_chunks(
        kb_id=kb_id,
        material_id=material_id,
        chunk_items=chunk_items,
        chunk_ids=[chunk_id],
    )

    assert first == [chunk_id]
    assert second == [chunk_id]
    assert db.flush_calls == 2
    assert [kind for kind, _payload in db.operations] == [
        "statement",
        "rows",
        "statement",
        "rows",
    ]
    assert db.operations[1][1] == db.operations[3][1]


@pytest.mark.asyncio
async def test_ingestion_doc_retry_after_outer_failure_produces_no_duplicates(
    monkeypatch,
) -> None:
    settings = _make_settings()
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    state = {
        "doc": SimpleNamespace(
            id=doc_id,
            kb_id=kb_id,
            source_ref=str(material_id),
            status=IngestionDocStatus.QUEUED,
            batch=None,
        ),
        "outbox": SimpleNamespace(status="pending"),
        "kb": SimpleNamespace(
            id=kb_id,
            index_config={
                "chunking": {
                    "general_strategy": ChunkingStrategy.MARKDOWN_HEADING.value,
                }
            },
        ),
        "material": SimpleNamespace(
            id=material_id,
            kb_id=kb_id,
            source_type=SimpleNamespace(value="file"),
        ),
        "stored_chunks": {},
        "mark_doc_succeeded_failures_remaining": 1,
    }
    sessionmaker = _FakeSessionmaker(state)
    milvus = _FakeMilvus()

    class _FakeIngestionBatchService:
        def __init__(self, db, *, object_storage, change_bus) -> None:  # noqa: ANN001
            self._db = db
            self._object_storage = object_storage
            self._change_bus = change_bus

        async def get_doc(self, *, doc_id: uuid.UUID, for_update: bool):  # noqa: FBT001, ANN201
            assert doc_id == state["doc"].id
            return state["doc"]

        async def get_doc_outbox(self, *, doc_id: uuid.UUID, for_update: bool):  # noqa: FBT001, ANN201
            assert doc_id == state["doc"].id
            return state["outbox"]

        async def mark_doc_running(self, *, doc) -> None:  # noqa: ANN001
            doc.status = IngestionDocStatus.PROCESSING

        async def recalculate_batch_for_doc(self, *, doc, reason: str) -> None:  # noqa: ANN001
            return None

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        async def mark_doc_succeeded(
            self,
            *,
            doc,
            outbox,  # noqa: ANN001
            chunk_count: int,
            context_failed_chunks: list[dict] | None = None,
        ) -> None:
            assert chunk_count == 1
            assert context_failed_chunks == []
            if state["mark_doc_succeeded_failures_remaining"] > 0:
                state["mark_doc_succeeded_failures_remaining"] -= 1
                raise RuntimeError("mark_doc_succeeded boom")
            doc.status = IngestionDocStatus.SUCCEEDED

        async def mark_doc_failed(
            self,
            *,
            doc,
            outbox,  # noqa: ANN001
            error_code: str,
            error_message: str,
            retryable: bool,
        ) -> None:
            assert error_code == "DOC_PROCESSING_ERROR"
            assert error_message == "mark_doc_succeeded boom"
            assert retryable is True
            doc.status = IngestionDocStatus.FAILED

    class _FakeChunkingEngine:
        def __init__(self, *, settings, embedding) -> None:  # noqa: ANN001
            self._settings = settings
            self._embedding = embedding

        async def split(self, _parsed, _index_config):
            return [ChunkItem(content="chunk-1", metadata={"window_id": 1})]

    class _FakeChunkStore:
        def __init__(self, _session) -> None:  # noqa: ANN001
            return None

        async def replace_material_chunks(
            self,
            *,
            kb_id: uuid.UUID,
            material_id: uuid.UUID,
            chunk_items,
            chunk_ids,  # noqa: ANN001
            **_kwargs,
        ):
            state["stored_chunks"][(kb_id, material_id)] = [item.content for item in chunk_items]
            return list(chunk_ids)

    @asynccontextmanager
    async def _fake_managed_task_resources(**_kwargs):
        yield SimpleNamespace(
            sessionmaker=sessionmaker,
            http_client=object(),
            embedding_http_client=object(),
            embedding_client=object(),
            object_storage=object(),
            milvus=milvus,
            url_crawler=None,
        )

    @asynccontextmanager
    async def _fake_change_bus(**_kwargs):
        yield object()

    async def _fake_parse_material(*_args, **_kwargs):
        return SimpleNamespace(text="parsed text", metadata={})

    async def _fake_generate_contexts_for_chunks(**_kwargs):
        return [
            SimpleNamespace(
                context="ctx",
                status="success",
                error=None,
                attempts=1,
            )
        ]

    class _FakeContextualEmbeddingService:
        def __init__(self, *, settings) -> None:  # noqa: ANN001
            self._settings = settings

    async def _fake_embed_inputs_with_concurrency(**_kwargs):
        return [[1.0]]

    monkeypatch.setattr(ingestion_batches, "get_settings", lambda: settings)
    monkeypatch.setattr(
        ingestion_batches,
        "managed_task_resources",
        _fake_managed_task_resources,
    )
    monkeypatch.setattr(
        ingestion_batches,
        "open_ingestion_batch_change_bus",
        _fake_change_bus,
    )
    monkeypatch.setattr(
        ingestion_batches,
        "IngestionBatchService",
        _FakeIngestionBatchService,
    )
    monkeypatch.setattr(ingestion_batches, "ChunkingEngine", _FakeChunkingEngine)
    monkeypatch.setattr(
        ingestion_batches,
        "ContextualEmbeddingService",
        _FakeContextualEmbeddingService,
    )
    monkeypatch.setattr(ingestion_batches, "ChunkPersistenceService", _FakeChunkStore)
    monkeypatch.setattr(ingestion_batches, "parse_material", _fake_parse_material)
    monkeypatch.setattr(
        ingestion_batches,
        "generate_contexts_for_chunks",
        _fake_generate_contexts_for_chunks,
    )
    monkeypatch.setattr(
        ingestion_batches,
        "build_embedding_inputs",
        lambda **_kwargs: ["chunk-1"],
    )
    monkeypatch.setattr(
        ingestion_batches,
        "embed_inputs_with_concurrency",
        _fake_embed_inputs_with_concurrency,
    )

    await ingestion_batches._run_ingestion_batch_doc(str(doc_id))
    state["doc"].status = IngestionDocStatus.QUEUED
    await ingestion_batches._run_ingestion_batch_doc(str(doc_id))

    material_key = (kb_id, material_id)
    milvus_key = (None, str(material_id))
    assert state["stored_chunks"][material_key] == ["chunk-1"]
    assert len(state["stored_chunks"][material_key]) == 1
    assert milvus.records_by_material[milvus_key][0]["content"] == "chunk-1"
    assert len(milvus.records_by_material[milvus_key]) == 1
    assert milvus.delete_calls == 2
    assert milvus.upsert_calls == 2
