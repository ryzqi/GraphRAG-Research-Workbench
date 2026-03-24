from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.chats import EvidenceItem, resolve_kb_chat_config
from app.services.knowledge_base_service import touch_kb_updated_at
from app.services.kb_chat_service import KbChatService


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl_values: dict[str, int] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[dict[str, object]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.ttl_values[key] = ex
        self.set_calls.append({"key": key, "value": value, "ex": ex})

    async def ttl(self, key: str) -> int:
        return self.ttl_values.get(key, -1)


class _FakeEmbedding:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [1.0, 0.0]
        self.calls: list[tuple[list[str], str]] = []

    async def embed(self, *, texts: list[str], stage: str) -> list[list[float]]:
        self.calls.append((texts, stage))
        return [list(self.vector) for _ in texts]


def _build_service() -> tuple[KbChatService, _FakeRedis]:
    service = KbChatService.__new__(KbChatService)
    redis = _FakeRedis()
    service._settings = SimpleNamespace(
        kb_chat_semantic_cache_enabled=True,
        kb_chat_semantic_cache_similarity_threshold=0.88,
        kb_chat_semantic_cache_soft_threshold=0.82,
        kb_chat_semantic_cache_shadow_mode=True,
        kb_chat_semantic_cache_ttl_seconds=24 * 60 * 60,
        kb_chat_semantic_cache_ttl_jitter_seconds=0,
        kb_chat_semantic_cache_max_items=128,
        embedding_model="text-embedding-3-small",
        context_history_max_messages=12,
    )
    service._redis = redis
    service._embedding = _FakeEmbedding()
    return service, redis


def _build_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000401"),
        session_type=SimpleNamespace(value="kb_chat"),
        selected_kb_ids=[uuid.UUID("00000000-0000-0000-0000-000000000402")],
        allow_external=False,
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
        citation_id="S1",
    )


def _build_v3_entry(
    *,
    entry_id: str,
    question: str,
    context_fingerprint: str,
    embedding: list[float],
    kb_version: str,
    hit_count: int = 0,
    metrics: dict[str, object] | None = None,
) -> dict[str, object]:
    evidence_item = _build_evidence_item()
    return {
        "entry_id": entry_id,
        "schema_version": "v3",
        "question": question,
        "question_normalized": question,
        "context_fingerprint": context_fingerprint,
        "answer": "缓存答案",
        "embedding": embedding,
        "evidence": [evidence_item.model_dump(mode="json")],
        "citation_ids": ["S1"],
        "evidence_fingerprint": [
            "00000000-0000-0000-0000-000000000402:00000000-0000-0000-0000-000000000403:00000000-0000-0000-0000-000000000404"
        ],
        "verified_level": "verified_direct",
        "hit_type": "strong_hit",
        "source_run_id": "run-source-1",
        "kb_version": kb_version,
        "answer_contract_version": "kb_chat_semantic_cache_v3",
        "created_at": "2026-03-24T10:00:00Z",
        "expires_at": "2026-03-25T10:00:00Z",
        "last_hit_at": None,
        "hit_count": hit_count,
        "stage_summaries": {"answer_review": {"passed": True}},
        "metrics": metrics or {},
    }


@pytest.mark.asyncio
async def test_lookup_rejects_same_question_when_context_fingerprint_differs() -> None:
    service, redis = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(**_: object) -> dict[str, object]:
        return {
            "summary_text": "当前问题围绕北京社保口径。",
            "recent_turns": [{"role": "user", "content": "先比较北京口径"}],
            "question": "缓存是否命中？",
        }

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    cache_key = service._semantic_cache_key(
        session,
        config_fingerprint=service._semantic_config_fingerprint(kb_chat_config),
        kb_version="kb-version-1",
    )
    redis.values[cache_key] = json.dumps(
        [
            {
                "entry_id": "entry-1",
                "schema_version": "v3",
                "question": "缓存是否命中？",
                "question_normalized": "缓存是否命中？",
                "context_fingerprint": service._semantic_cache_context_fingerprint(
                    {
                        "summary_text": "上下文已经切到上海口径。",
                        "recent_turns": [{"role": "user", "content": "先比较上海口径"}],
                        "question": "缓存是否命中？",
                    }
                ),
                "answer": "旧答案",
                "embedding": [1.0, 0.0],
                "evidence": [_build_evidence_item().model_dump(mode="json")],
                "citation_ids": ["S1"],
                "evidence_fingerprint": [
                    "00000000-0000-0000-0000-000000000402:00000000-0000-0000-0000-000000000403:00000000-0000-0000-0000-000000000404"
                ],
                "verified_level": "verified_direct",
                "kb_version": "kb-version-1",
                "answer_contract_version": "kb_chat_semantic_cache_v3",
                "created_at": "2026-03-24T10:00:00Z",
                "expires_at": "2026-03-25T10:00:00Z",
                "last_hit_at": None,
                "hit_count": 0,
                "stage_summaries": {},
                "metrics": {},
            }
        ],
        ensure_ascii=False,
    )
    redis.ttl_values[cache_key] = 7200

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
    )

    assert hit is None


@pytest.mark.asyncio
async def test_write_entry_v3_contains_context_and_version_fields() -> None:
    service, redis = _build_service()
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

    cache_key = service._semantic_cache_key(
        session,
        config_fingerprint=service._semantic_config_fingerprint(kb_chat_config),
        kb_version="kb-version-1",
    )
    payload = json.loads(redis.values[cache_key])

    assert len(payload) == 1
    entry = payload[0]
    assert entry["schema_version"] == "v3"
    assert entry["question"] == "缓存是否命中？"
    assert entry["question_normalized"] == "缓存是否命中？"
    assert entry["context_fingerprint"] == service._semantic_cache_context_fingerprint(
        pre_context
    )
    assert entry["citation_ids"] == ["S1"]
    assert entry["evidence_fingerprint"] == [
        "00000000-0000-0000-0000-000000000402:00000000-0000-0000-0000-000000000403:00000000-0000-0000-0000-000000000404"
    ]
    assert entry["verified_level"] == "verified_direct"
    assert entry["source_run_id"] == "run-source-1"
    assert entry["kb_version"] == "kb-version-1"
    assert entry["answer_contract_version"] == "kb_chat_semantic_cache_v3"
    assert entry["last_hit_at"] is None
    assert entry["hit_count"] == 0
    assert isinstance(entry["entry_id"], str) and entry["entry_id"]
    assert isinstance(entry["created_at"], str) and entry["created_at"]
    assert isinstance(entry["expires_at"], str) and entry["expires_at"]


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


def test_key_prefix_switches_to_v3_without_dual_read() -> None:
    service, _ = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)

    cache_key = service._semantic_cache_key(
        session,
        config_fingerprint=service._semantic_config_fingerprint(kb_chat_config),
        kb_version="kb-version-1",
    )

    assert cache_key.startswith("kb_chat:semantic_cache:v3:")
    assert ":v2:" not in cache_key


@pytest.mark.asyncio
async def test_lookup_returns_strong_hit_only_when_context_and_threshold_both_match() -> None:
    service, redis = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    pre_context = {
        "summary_text": "当前问题围绕北京社保口径。",
        "recent_turns": [{"role": "user", "content": "先比较北京口径"}],
        "question": "缓存是否命中？",
    }

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(**_: object) -> dict[str, object]:
        return dict(pre_context)

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    cache_key = service._semantic_cache_key(
        session,
        config_fingerprint=service._semantic_config_fingerprint(kb_chat_config),
        kb_version="kb-version-1",
    )
    redis.values[cache_key] = json.dumps(
        [
            _build_v3_entry(
                entry_id="entry-strong-1",
                question="缓存是否命中？",
                context_fingerprint=service._semantic_cache_context_fingerprint(pre_context),
                embedding=[0.91, math.sqrt(1 - 0.91**2)],
                kb_version="kb-version-1",
            )
        ],
        ensure_ascii=False,
    )
    redis.ttl_values[cache_key] = 7200

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
    )

    assert hit is not None
    assert hit.hit_type == "strong_hit"
    assert hit.entry_id == "entry-strong-1"
    assert hit.schema_version == "v3"


@pytest.mark.asyncio
async def test_soft_hit_shadow_mode_records_candidate_but_returns_none() -> None:
    service, redis = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    pre_context = {
        "summary_text": "当前问题围绕北京社保口径。",
        "recent_turns": [{"role": "user", "content": "先比较北京口径"}],
        "question": "缓存是否命中？",
    }

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(**_: object) -> dict[str, object]:
        return dict(pre_context)

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    cache_key = service._semantic_cache_key(
        session,
        config_fingerprint=service._semantic_config_fingerprint(kb_chat_config),
        kb_version="kb-version-1",
    )
    redis.values[cache_key] = json.dumps(
        [
            _build_v3_entry(
                entry_id="entry-soft-1",
                question="缓存是否命中？",
                context_fingerprint=service._semantic_cache_context_fingerprint(pre_context),
                embedding=[0.84, math.sqrt(1 - 0.84**2)],
                kb_version="kb-version-1",
            )
        ],
        ensure_ascii=False,
    )
    redis.ttl_values[cache_key] = 7200

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
    )

    assert hit is None
    shadow_candidate = getattr(service, "_semantic_cache_shadow_candidate", None)
    assert isinstance(shadow_candidate, dict)
    assert shadow_candidate["hit_type"] == "soft_hit"
    assert shadow_candidate["entry_id"] == "entry-soft-1"
    assert shadow_candidate["schema_version"] == "v3"
    assert shadow_candidate["kb_version"] == "kb-version-1"
    assert shadow_candidate["score"] == pytest.approx(0.84, abs=0.01)
    assert shadow_candidate["threshold"] == pytest.approx(0.88, abs=0.001)
    assert shadow_candidate["soft_threshold"] == pytest.approx(0.82, abs=0.001)


@pytest.mark.asyncio
async def test_hit_touch_updates_last_hit_at_and_hit_count() -> None:
    service, redis = _build_service()
    session = _build_session()
    kb_chat_config = resolve_kb_chat_config(raw=None)
    pre_context = {
        "summary_text": "当前问题围绕北京社保口径。",
        "recent_turns": [{"role": "user", "content": "先比较北京口径"}],
        "question": "缓存是否命中？",
    }

    async def _semantic_kb_version(_: object) -> str:
        return "kb-version-1"

    async def _load_semantic_cache_pre_context(**_: object) -> dict[str, object]:
        return dict(pre_context)

    service._semantic_kb_version = _semantic_kb_version
    service._load_semantic_cache_pre_context = _load_semantic_cache_pre_context

    cache_key = service._semantic_cache_key(
        session,
        config_fingerprint=service._semantic_config_fingerprint(kb_chat_config),
        kb_version="kb-version-1",
    )
    redis.values[cache_key] = json.dumps(
        [
            _build_v3_entry(
                entry_id="entry-hit-touch-1",
                question="缓存是否命中？",
                context_fingerprint=service._semantic_cache_context_fingerprint(pre_context),
                embedding=[1.0, 0.0],
                kb_version="kb-version-1",
                hit_count=2,
            )
        ],
        ensure_ascii=False,
    )
    redis.ttl_values[cache_key] = 7200

    hit = await service._semantic_cache_lookup(
        session=session,
        kb_chat_config=kb_chat_config,
        question="缓存是否命中？",
    )

    assert hit is not None
    payload = json.loads(redis.values[cache_key])
    entry = payload[0]
    assert entry["hit_count"] == 3
    assert isinstance(entry["last_hit_at"], str) and entry["last_hit_at"]
    assert entry["metrics"]["semantic_cache"]["hit"] is True
    assert entry["metrics"]["semantic_cache"]["hit_type"] == "strong_hit"
    assert entry["metrics"]["semantic_cache"]["entry_id"] == "entry-hit-touch-1"
    assert entry["metrics"]["semantic_cache"]["kb_version"] == "kb-version-1"
    assert entry["metrics"]["semantic_cache"]["schema_version"] == "v3"


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
