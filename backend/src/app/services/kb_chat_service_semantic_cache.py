from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models.chat_session import ChatSession
from app.models.knowledge_base import KnowledgeBase
from app.schemas.chats import (
    KbChatConfig,
    EvidenceItem,
    resolve_kb_chat_config,
)
from app.services.kb_chat_context_seed import (
    build_context_seed_from_history,
)
from app.services.evidence_guardrails import (
    is_stable_citation_id,
)
from app.services.semantic_cache.policy import (
    build_scope,
)
from app.services.semantic_cache.models import SemanticCacheHit, SemanticCacheScope
from app.services.semantic_cache.service import KbChatSemanticCacheService
from app.utils.text_sanitization import sanitize_visible_text

from app.services.kb_chat_service_contracts import (
    _KbChatExecution,
    _KbRetrievalBuffer,
    _SEMANTIC_CACHE_PRE_CONTEXT_MAX_TURNS,
)

logger = logging.getLogger(__name__)
def _resolve_session_kb_chat_config(self, session: ChatSession) -> KbChatConfig:
    raw = (
        session.kb_chat_config if isinstance(session.kb_chat_config, dict) else None
    )
    return resolve_kb_chat_config(raw=raw, settings=self._settings)

def _to_retrieval_overrides(self, config: KbChatConfig) -> dict[str, Any]:
    return {
        "retrieval_top_k": int(config.retrieval_top_k),
        "retrieval_rerank_top_k": int(config.retrieval_rerank_top_k),
        "hybrid_rrf_k": int(config.retrieval_hybrid_rrf_k),
        "parent_max_parents": int(config.retrieval_parent_max_parents),
        "parent_max_children_per_parent": int(
            config.retrieval_parent_max_children_per_parent
        ),
        "multiscale_per_window_top_k": int(
            config.retrieval_multiscale_per_window_top_k
        ),
        "multiscale_rrf_k": int(config.retrieval_multiscale_rrf_k),
        "multiscale_max_documents": int(config.retrieval_multiscale_max_documents),
        "multiscale_max_chunks_per_document": int(
            config.retrieval_multiscale_max_chunks_per_document
        ),
    }

def _semantic_cache_enabled(self) -> bool:
    semantic_cache_service = self._get_semantic_cache_service()
    if semantic_cache_service is not None:
        return semantic_cache_service.enabled()
    return bool(getattr(self._settings, "kb_chat_semantic_cache_enabled", True))

def _get_semantic_cache_service(self) -> KbChatSemanticCacheService | None:
    service = getattr(self, "_semantic_cache_service", None)
    if service is not None:
        return service
    embedding = getattr(self, "_embedding", None)
    settings = getattr(self, "_settings", None)
    if embedding is None or settings is None:
        return None
    service = KbChatSemanticCacheService(embedding=embedding, settings=settings)
    self._semantic_cache_service = service
    return service

def _semantic_cache_threshold(self) -> float:
    semantic_cache_service = self._get_semantic_cache_service()
    if semantic_cache_service is not None:
        return semantic_cache_service.similarity_threshold()
    return 0.88

def _semantic_cache_ttl_seconds(self) -> int:
    semantic_cache_service = self._get_semantic_cache_service()
    if semantic_cache_service is not None:
        return semantic_cache_service.ttl_seconds()
    return 24 * 60 * 60

async def _load_semantic_cache_pre_context(
    self,
    *,
    session_id: uuid.UUID,
    question: str,
    current_answer: str | None = None,
) -> dict[str, Any]:
    summary_service = getattr(self, "_summary_service", None)
    summary = (
        await summary_service.load_latest_summary(session_id)
        if summary_service is not None
        else None
    )
    summary_text = (
        sanitize_visible_text(str(getattr(summary, "content", "") or "")) or ""
    )
    history_limit = max(
        int(getattr(self._settings, "context_history_max_messages", 12) or 12),
        _SEMANTIC_CACHE_PRE_CONTEXT_MAX_TURNS * 2,
    )
    history = await self._load_history(session_id, limit=history_limit)
    return dict(
        build_context_seed_from_history(
            summary_text=summary_text,
            history=history,
            question=question,
            current_answer=current_answer,
            max_turns=_SEMANTIC_CACHE_PRE_CONTEXT_MAX_TURNS,
        )
    )

def _semantic_cache_citation_ids(self, 
    *,
    evidence: list[EvidenceItem],
    metrics: dict[str, Any],
) -> list[str]:
    raw_ids = metrics.get("citation_ids") if isinstance(metrics, dict) else None
    candidate_ids: list[str] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if not isinstance(item, str):
                continue
            normalized = item.strip().upper()
            if normalized and is_stable_citation_id(normalized):
                candidate_ids.append(normalized)
    if candidate_ids:
        return list(dict.fromkeys(candidate_ids))
    derived: list[str] = []
    for item in evidence:
        citation_id = str(item.citation_id or "").strip().upper()
        if citation_id and is_stable_citation_id(citation_id):
            derived.append(citation_id)
    return list(dict.fromkeys(derived))

def _semantic_cache_evidence_fingerprint(self, evidence: list[EvidenceItem]) -> list[str]:
    fingerprints: list[str] = []
    for item in evidence:
        if item.kb_id is None or item.material_id is None or item.chunk_id is None:
            continue
        fingerprints.append(f"{item.kb_id}:{item.material_id}:{item.chunk_id}")
    return list(dict.fromkeys(fingerprints))

def _semantic_cache_source_run_id(self, metrics: dict[str, Any]) -> str | None:
    gray_release_gate = (
        metrics.get("gray_release_gate") if isinstance(metrics, dict) else None
    )
    if isinstance(gray_release_gate, dict):
        source_run_id = gray_release_gate.get("source_run_id")
        if isinstance(source_run_id, str) and source_run_id.strip():
            return source_run_id.strip()
    semantic_cache_meta = (
        metrics.get("semantic_cache") if isinstance(metrics, dict) else None
    )
    if isinstance(semantic_cache_meta, dict):
        source_run_id = semantic_cache_meta.get("source_run_id")
        if isinstance(source_run_id, str) and source_run_id.strip():
            return source_run_id.strip()
    return None

def _semantic_config_fingerprint(self, config: KbChatConfig) -> str:
    raw = json.dumps(
        config.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

async def _semantic_kb_version(self, session: ChatSession) -> str:
    kb_ids = [uuid.UUID(str(kid)) for kid in (session.selected_kb_ids or [])]
    if not kb_ids:
        return "kb_none"
    stmt = (
        select(KnowledgeBase.id, KnowledgeBase.updated_at)
        .where(KnowledgeBase.id.in_(kb_ids))
        .order_by(KnowledgeBase.id.asc())
    )
    rows = (await self._db.execute(stmt)).all()
    payload: list[dict[str, str]] = [
        {"id": str(kid), "updated_at": ""} for kid in sorted(kb_ids, key=str)
    ]
    index_by_id = {item["id"]: idx for idx, item in enumerate(payload)}
    for row in rows:
        updated_at = row[1]
        kb_id = str(row[0])
        idx = index_by_id.get(kb_id)
        if idx is None:
            continue
        payload[idx] = {
            "id": kb_id,
            "updated_at": (
                updated_at.isoformat() if isinstance(updated_at, datetime) else ""
            ),
        }
    payload_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload_raw.encode("utf-8")).hexdigest()

def _build_semantic_cache_scope(
    self,
    *,
    session: ChatSession,
    kb_chat_config: KbChatConfig,
    kb_version: str,
) -> SemanticCacheScope:
    return build_scope(
        kb_ids=sorted(str(kid) for kid in (session.selected_kb_ids or [])),
        allow_external=bool(getattr(session, "allow_external", False)),
        mode=str(getattr(getattr(session, "mode", None), "value", "") or ""),
        config_fingerprint=self._semantic_config_fingerprint(kb_chat_config),
        kb_version=kb_version,
    )

async def _semantic_cache_lookup(
    self,
    *,
    session: ChatSession,
    kb_chat_config: KbChatConfig,
    question: str,
) -> tuple[SemanticCacheHit | None, list[float] | None]:
    if not self._semantic_cache_enabled():
        return None, None
    normalized_question = sanitize_visible_text(str(question or ""))
    if not normalized_question:
        return None, None
    semantic_cache_service = self._get_semantic_cache_service()
    if semantic_cache_service is None:
        return None, None
    try:
        kb_version = await self._semantic_kb_version(session)
    except Exception:
        kb_version = "kb_unknown"
    try:
        pre_context = await self._load_semantic_cache_pre_context(
            session_id=session.id,
            question=normalized_question,
        )
    except Exception:
        return None, None
    scope = self._build_semantic_cache_scope(
        session=session,
        kb_chat_config=kb_chat_config,
        kb_version=kb_version,
    )
    return await semantic_cache_service.lookup_with_vector(
        question=normalized_question,
        scope=scope,
        pre_context=pre_context,
    )

async def _write_semantic_cache_entry(
    self,
    *,
    session: ChatSession,
    kb_chat_config: KbChatConfig,
    question: str,
    answer: str,
    evidence: list[EvidenceItem],
    stage_summaries: dict[str, Any],
    metrics: dict[str, Any],
    question_vector: list[float] | None = None,
) -> None:
    if not self._semantic_cache_enabled():
        return
    semantic_cache_service = self._get_semantic_cache_service()
    if semantic_cache_service is None:
        return
    normalized_question = sanitize_visible_text(str(question or ""))
    normalized_answer = str(answer or "").strip()
    if not normalized_question or not normalized_answer:
        return

    try:
        kb_version = await self._semantic_kb_version(session)
    except Exception:
        kb_version = "kb_unknown"
    try:
        pre_context = await self._load_semantic_cache_pre_context(
            session_id=session.id,
            question=normalized_question,
            current_answer=normalized_answer,
        )
    except Exception:
        return
    citation_ids = self._semantic_cache_citation_ids(
        evidence=evidence,
        metrics=metrics if isinstance(metrics, dict) else {},
    )
    evidence_fingerprint = self._semantic_cache_evidence_fingerprint(evidence)
    if not citation_ids or not evidence_fingerprint:
        return
    scope = self._build_semantic_cache_scope(
        session=session,
        kb_chat_config=kb_chat_config,
        kb_version=kb_version,
    )
    await semantic_cache_service.store(
        question=normalized_question,
        answer=normalized_answer,
        scope=scope,
        pre_context=pre_context,
        evidence=[item.model_dump(mode="json") for item in evidence],
        citation_ids=citation_ids,
        evidence_fingerprint=evidence_fingerprint,
        stage_summaries=stage_summaries
        if isinstance(stage_summaries, dict)
        else {},
        metrics=metrics if isinstance(metrics, dict) else {},
        source_run_id=self._semantic_cache_source_run_id(
            metrics if isinstance(metrics, dict) else {}
        ),
        question_vector=question_vector,
    )

def _release_retrieval_buffer(self, exec_ctx: _KbChatExecution) -> None:
    buffer = getattr(exec_ctx, "retrieval_buffer", None)
    if isinstance(buffer, _KbRetrievalBuffer):
        buffer.release()
        return
    fallback_results = getattr(exec_ctx, "retrieval_results", None)
    if isinstance(fallback_results, list):
        fallback_results.clear()
    fallback_meta = getattr(exec_ctx, "retrieval_meta", None)
    if isinstance(fallback_meta, dict):
        fallback_meta.clear()
