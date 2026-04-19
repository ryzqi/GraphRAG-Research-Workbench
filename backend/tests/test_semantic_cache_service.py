from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest

from app.schemas.chats import EvidenceItem, EvidenceSourceKind
from app.services import kb_chat_service_semantic_cache as kb_semantic_cache
from app.services.semantic_cache.models import SemanticCacheScope
from app.services.semantic_cache.service import KbChatSemanticCacheService


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def embed(self, *, texts: list[str], stage: str) -> list[list[float]]:
        self.calls.append({"texts": list(texts), "stage": stage})
        return [[0.25, 0.5, 0.75]]


class _FakeSemanticCacheBackend:
    def __init__(self) -> None:
        self.lookup_requests = []
        self.store_requests = []

    async def lookup(self, request):  # noqa: ANN001
        self.lookup_requests.append(request)
        return None

    async def store(self, request):  # noqa: ANN001
        self.store_requests.append(request)

    def status(self) -> dict[str, object]:
        return {"status": "ok", "enabled": True}


def _semantic_cache_scope() -> SemanticCacheScope:
    return SemanticCacheScope(
        scope_fingerprint="scope-1",
        kb_version="kb-v1",
        mode="kb_chat",
        allow_external=False,
        config_fingerprint="cfg-1",
    )


@pytest.mark.asyncio
async def test_lookup_then_store_reuses_lookup_vector_on_cache_miss() -> None:
    embedding = _FakeEmbeddingClient()
    backend = _FakeSemanticCacheBackend()
    settings = SimpleNamespace(
        kb_chat_semantic_cache_enabled=True,
        kb_chat_semantic_cache_similarity_threshold=0.88,
        kb_chat_semantic_cache_ttl_seconds=600,
    )
    service = KbChatSemanticCacheService(
        embedding=embedding,
        settings=settings,
        backend=backend,
    )

    cache_hit, question_vector = await service.lookup_with_vector(
        question="解释一下 Redis 向量缓存",
        scope=_semantic_cache_scope(),
        pre_context={},
    )

    assert cache_hit is None
    assert question_vector == [0.25, 0.5, 0.75]

    await service.store(
        question="解释一下 Redis 向量缓存",
        answer="这是缓存答案",
        scope=_semantic_cache_scope(),
        pre_context={},
        evidence=[{"citation_id": "CIT-001"}],
        citation_ids=["CIT-001"],
        evidence_fingerprint=["kb-1:material-1:chunk-1"],
        stage_summaries={},
        metrics={},
        source_run_id=None,
        question_vector=question_vector,
    )

    assert [call["stage"] for call in embedding.calls] == ["semantic_cache_lookup"]
    assert len(backend.lookup_requests) == 1
    assert len(backend.store_requests) == 1
    assert backend.store_requests[0].question_vector == [0.25, 0.5, 0.75]


class _FakeKbChatSemanticCacheService:
    def __init__(self) -> None:
        self.store_calls: list[dict[str, object]] = []

    async def lookup_with_vector(self, **kwargs):  # noqa: ANN003
        return None, [0.5, 1.0]

    async def store(self, **kwargs):  # noqa: ANN003
        self.store_calls.append(dict(kwargs))


class _DummyKbChatService:
    def __init__(self) -> None:
        self._semantic_cache_service = _FakeKbChatSemanticCacheService()

    def _semantic_cache_enabled(self) -> bool:
        return True

    def _get_semantic_cache_service(self) -> _FakeKbChatSemanticCacheService:
        return self._semantic_cache_service

    async def _semantic_kb_version(self, session) -> str:  # noqa: ANN001
        del session
        return "kb-v1"

    async def _load_semantic_cache_pre_context(self, **kwargs):  # noqa: ANN003
        return {}

    def _build_semantic_cache_scope(self, **kwargs):  # noqa: ANN003
        return _semantic_cache_scope()

    def _semantic_cache_citation_ids(self, **kwargs):  # noqa: ANN003
        return ["CIT-001"]

    def _semantic_cache_evidence_fingerprint(self, evidence):  # noqa: ANN001
        del evidence
        return ["kb-1:material-1:chunk-1"]

    def _semantic_cache_source_run_id(self, metrics):  # noqa: ANN001
        del metrics
        return None


@pytest.mark.asyncio
async def test_write_semantic_cache_entry_forwards_lookup_vector_to_store() -> None:
    service = _DummyKbChatService()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=SimpleNamespace(value="kb_chat"),
    )
    evidence = [
        EvidenceItem(
            source_kind=EvidenceSourceKind.KB,
            kb_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            locator=None,
            excerpt="证据摘要",
            citation_id="CIT-001",
        )
    ]

    cache_hit, question_vector = await kb_semantic_cache._semantic_cache_lookup(
        service,
        session=session,
        kb_chat_config=object(),
        question="缓存 miss 时复用 embedding 吗？",
    )

    assert cache_hit is None
    assert question_vector == [0.5, 1.0]

    await kb_semantic_cache._write_semantic_cache_entry(
        service,
        session=session,
        kb_chat_config=object(),
        question="缓存 miss 时复用 embedding 吗？",
        answer="会把 lookup 的向量传给 store。",
        evidence=evidence,
        stage_summaries={},
        metrics={},
        question_vector=question_vector,
    )

    assert len(service._semantic_cache_service.store_calls) == 1
    assert service._semantic_cache_service.store_calls[0]["question_vector"] == [
        0.5,
        1.0,
    ]
