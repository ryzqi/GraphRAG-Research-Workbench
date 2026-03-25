from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.chats import EvidenceItem, resolve_kb_chat_config
from app.services.knowledge_base_service import touch_kb_updated_at
from app.services.kb_chat_service import KbChatService
from app.services.semantic_cache.models import (
    SemanticCacheHit,
    SemanticCacheLookupRequest,
    SemanticCacheStoreRequest,
)
from app.services.semantic_cache.policy import (
    SEMANTIC_CACHE_HIT_TYPE_STRONG,
    SEMANTIC_CACHE_SCHEMA_VERSION,
)
from app.services.semantic_cache.service import KbChatSemanticCacheService


class _FakeSemanticCacheBackend:
    def __init__(self) -> None:
        self.lookup_requests: list[SemanticCacheLookupRequest] = []
        self.store_requests: list[SemanticCacheStoreRequest] = []

    async def lookup(self, request: SemanticCacheLookupRequest) -> SemanticCacheHit | None:
        self.lookup_requests.append(request)
        best_request: SemanticCacheStoreRequest | None = None
        best_score = -1.0
        for candidate in self.store_requests:
            if candidate.scope.scope_fingerprint != request.scope.scope_fingerprint:
                continue
            if candidate.context.mode != request.context.mode:
                continue
            if (
                candidate.context.mode == "contextual"
                and candidate.context.signature != request.context.signature
            ):
                continue
            score = _cosine_similarity(candidate.question_vector, request.question_vector)
            if score >= request.similarity_threshold and score > best_score:
                best_score = score
                best_request = candidate
        if best_request is None:
            return None
        return SemanticCacheHit(
            answer=best_request.answer,
            evidence=best_request.evidence,
            stage_summaries=best_request.stage_summaries,
            metrics=best_request.metrics,
            score=best_score,
            threshold=request.similarity_threshold,
            ttl_seconds=request.ttl_seconds,
            entry_id="fake-entry-1",
            schema_version=SEMANTIC_CACHE_SCHEMA_VERSION,
            hit_type=SEMANTIC_CACHE_HIT_TYPE_STRONG,
            created_at="2026-03-24T10:00:00Z",
            context_fingerprint=best_request.context.signature,
            kb_version=best_request.scope.kb_version,
        )

    async def store(self, request: SemanticCacheStoreRequest) -> None:
        self.store_requests = [
            item
            for item in self.store_requests
            if not (
                item.scope.scope_fingerprint == request.scope.scope_fingerprint
                and item.context.mode == request.context.mode
                and item.context.signature == request.context.signature
                and item.question == request.question
            )
        ]
        self.store_requests.insert(0, request)


class _FakeEmbedding:
    def __init__(self, vectors_by_text: dict[str, list[float]] | None = None) -> None:
        self.vectors_by_text = vectors_by_text or {}
        self.calls: list[tuple[list[str], str]] = []

    async def embed(self, *, texts: list[str], stage: str) -> list[list[float]]:
        self.calls.append((texts, stage))
        return [list(self.vectors_by_text.get(text, [1.0, 0.0])) for text in texts]


class _StaticSemanticCacheService:
    def __init__(self, *, threshold: float, ttl_seconds: int) -> None:
        self._threshold = threshold
        self._ttl_seconds = ttl_seconds

    def similarity_threshold(self) -> float:
        return self._threshold

    def ttl_seconds(self) -> int:
        return self._ttl_seconds


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for l_value, r_value in zip(left, right, strict=False):
        dot += l_value * r_value
        left_norm += l_value * l_value
        right_norm += r_value * r_value
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _build_service(
    *,
    vectors_by_text: dict[str, list[float]] | None = None,
) -> tuple[KbChatService, _FakeSemanticCacheBackend]:
    service = KbChatService.__new__(KbChatService)
    backend = _FakeSemanticCacheBackend()
    service._settings = SimpleNamespace(
        kb_chat_semantic_cache_enabled=True,
        kb_chat_semantic_cache_similarity_threshold=0.88,
        kb_chat_semantic_cache_ttl_seconds=24 * 60 * 60,
        kb_chat_semantic_cache_index_name="kb_chat_semantic_cache_test",
        embedding_model="text-embedding-3-small",
        context_history_max_messages=12,
    )
    service._embedding = _FakeEmbedding(vectors_by_text=vectors_by_text)
    service._semantic_cache_service = KbChatSemanticCacheService(
        embedding=service._embedding,
        settings=service._settings,
        backend=backend,
    )
    return service, backend


def _build_session(
    *,
    selected_kb_ids: list[uuid.UUID] | None = None,
    allow_external: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000401"),
        session_type=SimpleNamespace(value="kb_chat"),
        selected_kb_ids=selected_kb_ids
        or [uuid.UUID("00000000-0000-0000-0000-000000000402")],
        allow_external=allow_external,
        mode=SimpleNamespace(value="single_agent"),
    )


def _build_evidence_item() -> EvidenceItem:
    return EvidenceItem(
        source_kind="kb",
        kb_id=uuid.UUID("00000000-0000-0000-0000-000000000402"),
        material_id=uuid.UUID("00000000-0000-0000-0000-000000000403"),
        chunk_id=uuid.UUID("00000000-0000-0000-0000-000000000404"),
        locator={"filename": "cache-source.pdf"},
        excerpt="可复用证据",
        source_excerpt="可复用证据的原始上下文",
        citation_id="S1",
    )


def test_threshold_and_ttl_delegate_to_semantic_cache_service() -> None:
    service = KbChatService.__new__(KbChatService)
    service._settings = SimpleNamespace(
        kb_chat_semantic_cache_similarity_threshold=0.88,
        kb_chat_semantic_cache_ttl_seconds=24 * 60 * 60,
    )
    service._semantic_cache_service = _StaticSemanticCacheService(
        threshold=0.73,
        ttl_seconds=321,
    )

    assert service._semantic_cache_threshold() == 0.73
    assert service._semantic_cache_ttl_seconds() == 321


@pytest.mark.asyncio
async def test_lookup_hits_for_standalone_paraphrase_with_same_scope() -> None:
    service, _ = _build_service(
        vectors_by_text={
            "比较 CoT 和 ToT 的区别": [1.0, 0.0],
            "CoT 和 ToT 两个框架有什么差异": [1.0, 0.0],
        }
    )
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    evidence_item = _build_evidence_item()

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(
        *,
        session_id: object,
        question: str,
        current_answer: str | None = None,
    ) -> dict[str, object]:
        _ = (session_id, current_answer)
        return {"summary_text": "", "recent_turns": [], "question": question}

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    await service._write_semantic_cache_entry(
        session=session,
        kb_chat_config=kb_chat_config,
        question="比较 CoT 和 ToT 的区别",
        answer="这是可复用答案。",
        evidence=[evidence_item],
        stage_summaries={"answer_review": {"passed": True}},
        metrics={
            "citation_ids": ["S1"],
            "evidence_chunk_ids": [str(evidence_item.chunk_id)],
            "gray_release_gate": {"source_run_id": "run-source-1"},
        },
    )

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="CoT 和 ToT 两个框架有什么差异",
    )

    assert hit is not None
    assert hit.hit_type == "strong_hit"
    assert hit.answer == "这是可复用答案。"
    assert hit.evidence[0]["source_excerpt"] == "可复用证据的原始上下文"


@pytest.mark.asyncio
async def test_lookup_after_write_remains_hit_when_same_turn_enters_history() -> None:
    service, _ = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    evidence_item = _build_evidence_item()

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    def _pre_context(*, include_current_turn: bool, question: str) -> dict[str, object]:
        recent_turns = [
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮答案"},
        ]
        if include_current_turn:
            recent_turns.extend(
                [
                    {"role": "user", "content": "缓存是否命中？"},
                    {"role": "assistant", "content": "这是可复用答案。"},
                ]
            )
        return {
            "summary_text": "会话一直围绕同一个知识点展开。",
            "recent_turns": recent_turns,
            "question": question,
        }

    async def _load_semantic_cache_pre_context(
        *,
        session_id: object,
        question: str,
        current_answer: str | None = None,
    ) -> dict[str, object]:
        _ = session_id
        return _pre_context(include_current_turn=current_answer is None, question=question)

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    await service._write_semantic_cache_entry(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
        answer="这是可复用答案。",
        evidence=[evidence_item],
        stage_summaries={"answer_review": {"passed": True}},
        metrics={
            "citation_ids": ["S1"],
            "evidence_chunk_ids": [str(evidence_item.chunk_id)],
            "gray_release_gate": {"source_run_id": "run-source-1"},
        },
    )

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
    )

    assert hit is not None
    assert hit.answer == "这是可复用答案。"


@pytest.mark.asyncio
async def test_contextual_follow_up_misses_when_context_signature_differs() -> None:
    service, _ = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    evidence_item = _build_evidence_item()

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(
        *,
        session_id: object,
        question: str,
        current_answer: str | None = None,
    ) -> dict[str, object]:
        _ = (session_id, current_answer)
        if question == "它们分别适合什么场景？":
            return {
                "summary_text": "当前在比较 ReAct 和 AutoGPT。",
                "recent_turns": [{"role": "user", "content": "先比较 ReAct 和 AutoGPT"}],
                "question": question,
            }
        return {
            "summary_text": "当前在比较 CoT 和 ToT。",
            "recent_turns": [{"role": "user", "content": "先比较 CoT 和 ToT"}],
            "question": question,
        }

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    await service._write_semantic_cache_entry(
        session=session,
        kb_chat_config=kb_chat_config,
        question="它们分别适合哪些场景？",
        answer="这是上下文相关答案。",
        evidence=[evidence_item],
        stage_summaries={"answer_review": {"passed": True}},
        metrics={
            "citation_ids": ["S1"],
            "evidence_chunk_ids": [str(evidence_item.chunk_id)],
            "gray_release_gate": {"source_run_id": "run-source-1"},
        },
    )

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="它们分别适合什么场景？",
    )

    assert hit is None


@pytest.mark.asyncio
async def test_write_entry_records_scope_context_and_contract_fields() -> None:
    service, backend = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    evidence_item = _build_evidence_item()
    pre_context = {
        "summary_text": "当前会话在比较北京和上海的社保口径。",
        "recent_turns": [{"role": "user", "content": "先比较北京社保口径"}],
        "question": "缓存是否命中？",
    }

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(**_: object) -> dict[str, object]:
        return dict(pre_context)

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    await service._write_semantic_cache_entry(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
        answer="这是可复用答案。",
        evidence=[evidence_item],
        stage_summaries={"answer_review": {"passed": True}},
        metrics={
            "citation_ids": ["S1"],
            "evidence_chunk_ids": [str(evidence_item.chunk_id)],
            "gray_release_gate": {"source_run_id": "run-source-1"},
        },
    )

    assert len(backend.store_requests) == 1
    request = backend.store_requests[0]
    assert request.scope.kb_version == "kb-version-1"
    assert request.scope.allow_external is False
    assert request.context.mode == "standalone"
    assert request.citation_ids == ["S1"]
    assert request.evidence[0]["source_excerpt"] == "可复用证据的原始上下文"
    assert request.evidence_fingerprint == [
        "00000000-0000-0000-0000-000000000402:00000000-0000-0000-0000-000000000403:00000000-0000-0000-0000-000000000404"
    ]
    assert request.source_run_id == "run-source-1"


def test_write_admission_rejects_missing_evidence_or_citation_ids() -> None:
    service, _ = _build_service()

    missing_evidence_reason = service._semantic_cache_entry_admission_reason(
        status="succeeded",
        clarification_payload=None,
        routing_decisions=None,
        reflection=None,
        degrade_reason=None,
        answer="这是答案。",
        evidence=[],
        metrics={"citation_ids": ["S1"], "evidence_chunk_ids": ["chunk-1"]},
        stage_summaries={"answer_review": {"passed": True}},
    )
    assert missing_evidence_reason == "missing_evidence"

    missing_citation_reason = service._semantic_cache_entry_admission_reason(
        status="succeeded",
        clarification_payload=None,
        routing_decisions=None,
        reflection=None,
        degrade_reason=None,
        answer="这是答案。",
        evidence=[_build_evidence_item()],
        metrics={"citation_ids": [], "evidence_chunk_ids": ["chunk-1"]},
        stage_summaries={"answer_review": {"passed": True}},
    )
    assert missing_citation_reason == "missing_citation_ids"


@pytest.mark.asyncio
async def test_scope_isolation_prevents_cross_kb_hit() -> None:
    service, _ = _build_service()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    evidence_item = _build_evidence_item()
    source_session = _build_session()
    target_session = _build_session(
        selected_kb_ids=[uuid.UUID("00000000-0000-0000-0000-000000000499")]
    )

    async def _semantic_kb_version(session: object) -> str:
        selected = getattr(session, "selected_kb_ids", [])
        return f"kb-version-{selected[0]}"

    async def _load_semantic_cache_pre_context(**kwargs: object) -> dict[str, object]:
        question = str(kwargs.get("question") or "")
        return {"summary_text": "", "recent_turns": [], "question": question}

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    await service._write_semantic_cache_entry(
        session=source_session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
        answer="这是源知识库答案。",
        evidence=[evidence_item],
        stage_summaries={"answer_review": {"passed": True}},
        metrics={
            "citation_ids": ["S1"],
            "evidence_chunk_ids": [str(evidence_item.chunk_id)],
            "gray_release_gate": {"source_run_id": "run-source-1"},
        },
    )

    hit = await service._semantic_cache_lookup(
        session=target_session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
    )

    assert hit is None


@pytest.mark.asyncio
async def test_kb_version_rolls_when_updated_at_changes() -> None:
    service, _ = _build_service()
    session = _build_session()

    class _FakeResult:
        def __init__(self, rows: list[tuple[uuid.UUID, datetime]]) -> None:
            self._rows = rows

        def all(self) -> list[tuple[uuid.UUID, datetime]]:
            return list(self._rows)

    class _FakeDb:
        def __init__(self, rows: list[tuple[uuid.UUID, datetime]]) -> None:
            self.rows = rows

        async def execute(self, _: object) -> _FakeResult:
            return _FakeResult(self.rows)

    first_updated_at = datetime(2026, 3, 24, 10, 0, tzinfo=timezone.utc)
    second_updated_at = datetime(2026, 3, 24, 11, 0, tzinfo=timezone.utc)
    service._db = _FakeDb([(session.selected_kb_ids[0], first_updated_at)])
    first_version = await service._semantic_kb_version(session)

    service._db.rows = [(session.selected_kb_ids[0], second_updated_at)]
    second_version = await service._semantic_kb_version(session)

    assert first_version != second_version


@pytest.mark.asyncio
async def test_touch_kb_updated_at_updates_timestamp() -> None:
    kb_id = uuid.UUID("00000000-0000-0000-0000-000000000499")
    kb = SimpleNamespace(
        id=kb_id,
        updated_at=datetime(2026, 3, 24, 10, 0, tzinfo=timezone.utc),
    )

    class _FakeDb:
        def __init__(self) -> None:
            self.flush_calls = 0

        async def get(self, _: object, target_kb_id: uuid.UUID) -> object | None:
            return kb if target_kb_id == kb_id else None

        async def flush(self) -> None:
            self.flush_calls += 1

    fake_db = _FakeDb()

    await touch_kb_updated_at(fake_db, kb_id)

    assert kb.updated_at > datetime(2026, 3, 24, 10, 0, tzinfo=timezone.utc)
    assert fake_db.flush_calls == 1
