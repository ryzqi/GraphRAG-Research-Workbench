"""Retrieval service with Milvus-backed search and optional cache/rewrite/rerank."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingCallError, EmbeddingClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.redis_client import RedisClient
from app.integrations.rerank_client import RerankClient
from app.models.document_chunk import DocumentChunk
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial
from app.schemas.chats import EvidenceItem, EvidenceSourceKind
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.schemas.query_enhancement import QueryHitSource, QueryItem
from app.services.query_dependent_collections import collection_name_for_window
from app.services.query_rewrite_service import (
    HYDE_AGGREGATION,
    HYDE_NUM_HYPOTHESES,
    QueryRewriteService,
    RewriteResult,
    build_query_items,
)

logger = logging.getLogger(__name__)
QUERY_FANOUT_CONCURRENCY = 3
DEDUP_EMBEDDING_SIMILARITY_THRESHOLD = 0.95
DEFAULT_RESULT_EXCERPT_MAX_CHARS = 500
EXPANDED_RESULT_EXCERPT_MAX_CHARS = 4000


@dataclass(slots=True)
class RetrievedChunk:
    id: uuid.UUID
    kb_id: uuid.UUID
    material_id: uuid.UUID
    content: str
    context: str | None
    locator: dict | None
    metadata: dict | None
    chunk_role: str | None
    parent_chunk_id: str | None
    child_seq: int | None
    chunk_index: int | None = None
    heading_path: str | None = None
    global_chunk_order: int | None = None


@dataclass(slots=True)
class RetrievalResult:
    chunk: RetrievedChunk
    score: float
    context_text: str | None = None


@dataclass(slots=True)
class RetrievalStats:
    query: str
    normalized_query: str
    effective_query: str
    top_k: int
    min_score: float | None
    total_hits: int
    filtered_count: int
    returned_count: int
    cache_hit: bool = False
    rewrite_enabled: bool = False
    rewrite_applied: bool = False
    rewrite_reason: str | None = None
    rewrite_latency_ms: int | None = None
    hybrid_enabled: bool = False
    rerank_enabled: bool = False
    rerank_applied: bool = False
    rerank_reason: str | None = None
    rerank_latency_ms: int | None = None
    reason: str | None = None


@dataclass(slots=True)
class RetrievalFeatureFlags:
    query_rewrite_enabled: bool
    hybrid_enabled: bool
    rerank_enabled: bool


@dataclass(slots=True)
class RetrievalRuntimeOverrides:
    hybrid_rrf_k: int
    retrieval_top_k: int
    retrieval_rerank_top_k: int
    parent_max_parents: int
    parent_max_children_per_parent: int
    multiscale_per_window_top_k: int
    multiscale_rrf_k: int
    multiscale_max_documents: int
    multiscale_max_chunks_per_document: int


@dataclass(slots=True)
class RetrievalLayerDraft:
    """Unified retrieval layer output (for agentic state + legacy tool compatibility).

    - retrieval_candidates: RRF-fused (global) candidates after caps, before rerank
    - reranked_candidates: rerank output capped to Top-N (or RRF Top-N fallback)
    - evidence_items: evidence draft for Top-N (chunk-level, with provenance)
    - results: final RetrievalResult list for legacy callers (Top-N)
    """

    retrieval_candidates: list[dict]
    reranked_candidates: list[dict]
    evidence_items: list[dict]
    results: list["RetrievalResult"]
    stats: dict[str, object]


class RetrievalService:
    def __init__(
        self,
        db: AsyncSession,
        milvus: MilvusClient,
        embedding: EmbeddingClient,
        redis: RedisClient | None = None,
        query_rewriter: QueryRewriteService | None = None,
        reranker: RerankClient | None = None,
    ) -> None:
        self._db = db
        self._milvus = milvus
        self._embedding = embedding
        self._redis = redis
        self._query_rewriter = query_rewriter
        self._reranker = reranker
        self._settings = get_settings()
        self._last_stats: RetrievalStats | None = None
        self._last_layer_draft: RetrievalLayerDraft | None = None
        self._db_lock = asyncio.Lock()

    @property
    def last_stats(self) -> RetrievalStats | None:
        return self._last_stats

    @property
    def last_layer_draft(self) -> RetrievalLayerDraft | None:
        """Last unified retrieval layer draft for the most recent retrieval call."""
        return self._last_layer_draft

    @staticmethod
    def _make_deadline(timeout_seconds: float | None) -> float | None:
        if timeout_seconds is None:
            return None
        return time.monotonic() + max(float(timeout_seconds), 0.0)

    @staticmethod
    def _remaining_seconds(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    @staticmethod
    def _effective_timeout(
        *,
        deadline: float | None,
        per_call_timeout: float | None,
    ) -> float | None:
        remaining = RetrievalService._remaining_seconds(deadline)
        if remaining is None:
            return per_call_timeout
        if per_call_timeout is None:
            return remaining
        return max(0.0, min(float(per_call_timeout), remaining))

    @staticmethod
    async def _run_with_timeout(coro, timeout_seconds: float | None):
        if timeout_seconds is None:
            return await coro
        if timeout_seconds <= 0:
            raise asyncio.TimeoutError()
        return await asyncio.wait_for(coro, timeout=timeout_seconds)

    async def _db_execute(self, stmt):
        if self._db is None:
            raise RuntimeError("db_not_configured")
        async with self._db_lock:
            return await self._db.execute(stmt)

    @staticmethod
    def _empty_layer_draft(reason: str | None = None) -> RetrievalLayerDraft:
        stats: dict[str, object] = {
            "hybrid_hits": 0,
            "rrf_candidates": 0,
            "rerank_applied": False,
            "optional_embedding_skips": [],
        }
        if reason:
            stats["reason"] = reason
        return RetrievalLayerDraft(
            retrieval_candidates=[],
            reranked_candidates=[],
            evidence_items=[],
            results=[],
            stats=stats,
        )

    @staticmethod
    def _strip_file_extension(name: str) -> str:
        raw = (name or "").strip()
        if not raw:
            return ""
        stem = PurePosixPath(raw).stem
        if stem == raw:
            stem = PureWindowsPath(raw).stem
        return stem.strip() or raw

    @staticmethod
    def _normalize_citation_label(value: str) -> str:
        cleaned = value.replace("[", " ").replace("]", " ")
        normalized = " ".join(cleaned.split())
        return normalized.strip()

    @staticmethod
    def _extract_filename_from_locator(locator: dict | None) -> str | None:
        if not isinstance(locator, dict):
            return None
        raw = locator.get("filename")
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        if not value:
            return None
        # Normalize both POSIX/Windows style path separators.
        value = value.replace("\\", "/")
        return value.rsplit("/", 1)[-1] or None

    @classmethod
    def _derive_citation_label(
        cls, *, locator: dict | None, material_title: str | None
    ) -> str:
        filename = cls._extract_filename_from_locator(locator)
        if filename:
            label = cls._normalize_citation_label(cls._strip_file_extension(filename))
            if label:
                return label

        if isinstance(material_title, str) and material_title.strip():
            label = cls._normalize_citation_label(
                cls._strip_file_extension(material_title.strip())
            )
            if label:
                return label

        return "material"

    async def _load_material_titles_by_id(
        self, material_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not material_ids or self._db is None:
            return {}
        stmt = select(SourceMaterial.id, SourceMaterial.title).where(
            SourceMaterial.id.in_(list(material_ids))
        )
        result = await self._db_execute(stmt)
        title_by_id: dict[uuid.UUID, str] = {}
        for row in result.all():
            material_id = row[0]
            title = row[1]
            if isinstance(title, str) and title.strip():
                title_by_id[material_id] = title.strip()
        return title_by_id

    async def _ensure_chunk_citation_labels(self, chunks: list[RetrievedChunk]) -> None:
        if not chunks:
            return
        material_ids = {chunk.material_id for chunk in chunks}
        title_by_id = await self._load_material_titles_by_id(material_ids)
        for chunk in chunks:
            locator = chunk.locator if isinstance(chunk.locator, dict) else {}
            label = self._derive_citation_label(
                locator=locator,
                material_title=title_by_id.get(chunk.material_id),
            )
            if not isinstance(chunk.locator, dict):
                chunk.locator = {}
            chunk.locator["citation_label"] = label

    async def _hydrate_chunks_from_postgres(self, chunks: list[RetrievedChunk]) -> None:
        """Backfill chunk fields when Milvus hits lack output_fields.

        Prefer Milvus output_fields; only query Postgres when fields are missing.
        """

        if not chunks or self._db is None:
            return

        missing: set[uuid.UUID] = set()
        for c in chunks:
            missing_content = not c.content
            missing_locator = c.locator is None or c.locator == {}
            missing_position = (
                c.chunk_index is None
                or c.global_chunk_order is None
                or c.heading_path is None
            )
            if missing_content or missing_locator or missing_position:
                missing.add(c.id)
        if not missing:
            return

        stmt = select(
            DocumentChunk.id,
            DocumentChunk.raw_text,
            DocumentChunk.locator,
            DocumentChunk.chunk_index,
            DocumentChunk.heading_path,
            DocumentChunk.global_chunk_order,
        ).where(DocumentChunk.id.in_(list(missing)))
        result = await self._db_execute(stmt)
        by_id: dict[
            uuid.UUID,
            tuple[str, dict | None, int | None, str | None, int | None],
        ] = {
            row.id: (
                row.raw_text,
                row.locator,
                row.chunk_index,
                row.heading_path,
                row.global_chunk_order,
            )
            for row in result.all()
        }
        for c in chunks:
            got = by_id.get(c.id)
            if not got:
                continue
            text, locator, chunk_index, heading_path, global_chunk_order = got
            if not c.content:
                c.content = text or ""
            if (c.locator is None or c.locator == {}) and locator:
                c.locator = locator
            if c.chunk_index is None and isinstance(chunk_index, int):
                c.chunk_index = chunk_index
            if c.heading_path is None and isinstance(heading_path, str):
                c.heading_path = heading_path
            if c.global_chunk_order is None and isinstance(global_chunk_order, int):
                c.global_chunk_order = global_chunk_order

    @staticmethod
    def _first_markdown_heading_match(text: str) -> re.Match[str] | None:
        if not isinstance(text, str) or not text.strip():
            return None
        return re.search(r"(?m)^(#{2,6})\s+(.+?)\s*$", text)

    @classmethod
    def _first_markdown_heading(cls, text: str) -> tuple[int, str] | None:
        match = cls._first_markdown_heading_match(text)
        if match is None:
            return None
        return len(match.group(1)), match.group(2).strip()

    @staticmethod
    def _is_single_main_query(query_items: list[QueryItem]) -> bool:
        if len(query_items) != 1:
            return False
        item = query_items[0]
        if not isinstance(item, dict):
            return False
        kind = str(item.get("kind") or "").strip().lower()
        query = str(item.get("query") or "").strip()
        return kind == "main" and bool(query)

    async def _expand_direct_section_neighbors(
        self,
        results: list[RetrievalResult],
        *,
        query_items: list[QueryItem],
        top_n: int,
        timeout_seconds: float | None = None,
        hits_by_key: dict[tuple[str, str, str], list[QueryHitSource]] | None = None,
    ) -> list[RetrievalResult]:
        if (
            not results
            or self._db is None
            or not self._is_single_main_query(query_items)
        ):
            return results

        seed = results[0].chunk
        if (
            seed.global_chunk_order is None
            or seed.chunk_role == "child"
            or not isinstance(seed.content, str)
            or not seed.content.strip()
        ):
            return results

        heading = self._first_markdown_heading(seed.content)
        if heading is None:
            return results
        seed_level, _ = heading
        boundary_level = max(2, seed_level - 1)
        max_scan_rows = max(8, min(max(top_n * 2, top_n + 4), 24))

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.kb_id,
                DocumentChunk.material_id,
                DocumentChunk.raw_text,
                DocumentChunk.locator,
                DocumentChunk.chunk_index,
                DocumentChunk.heading_path,
                DocumentChunk.global_chunk_order,
            )
            .where(
                DocumentChunk.kb_id == seed.kb_id,
                DocumentChunk.material_id == seed.material_id,
                DocumentChunk.global_chunk_order >= int(seed.global_chunk_order),
                DocumentChunk.global_chunk_order
                <= int(seed.global_chunk_order) + max_scan_rows,
            )
            .order_by(DocumentChunk.global_chunk_order.asc())
        )

        rows = await self._run_with_timeout(self._db_execute(stmt), timeout_seconds)
        existing_ids = {row.chunk.id for row in results}
        expanded = list(results)
        after_seed = False
        section_parts = [seed.content.strip()]
        expansion_limit = max(top_n, 6)

        for row in rows.all():
            row_order = row.global_chunk_order
            if not isinstance(row_order, int):
                continue
            if row_order == seed.global_chunk_order:
                after_seed = True
                continue
            if not after_seed:
                continue

            text = row.raw_text or ""
            row_heading = self._first_markdown_heading(text)
            if row_heading is not None and row_heading[0] <= boundary_level:
                break
            if not text.strip():
                continue
            section_parts.append(text.strip())
            if row.id in existing_ids:
                continue
            if len(expanded) >= expansion_limit:
                continue

            chunk = RetrievedChunk(
                id=row.id,
                kb_id=row.kb_id,
                material_id=row.material_id,
                content=text,
                context=None,
                locator=row.locator,
                metadata=None,
                chunk_role="default",
                parent_chunk_id=None,
                child_seq=None,
                chunk_index=row.chunk_index if isinstance(row.chunk_index, int) else None,
                heading_path=row.heading_path if isinstance(row.heading_path, str) else None,
                global_chunk_order=row_order,
            )
            expanded.append(
                RetrievalResult(
                    chunk=chunk,
                    score=max(results[0].score - 0.001 * len(expanded), 0.0),
                    context_text=text,
                )
            )
            existing_ids.add(row.id)
            if isinstance(hits_by_key, dict):
                hits_by_key.setdefault(self._candidate_key(chunk), [])

        if len(section_parts) > 1:
            merged_section = "\n\n".join(part for part in section_parts if part)
            expanded[0].context_text = merged_section

        return expanded

    async def _populate_result_context_from_heading_path(
        self,
        result: RetrievalResult,
        *,
        timeout_seconds: float | None = None,
        scan_radius: int = 8,
    ) -> RetrievalResult:
        if self._db is None:
            return result

        seed = result.chunk
        seed_content = (seed.content or "").strip()
        existing_context = (result.context_text or "").strip()
        heading_path = str(seed.heading_path or "").strip()
        if (
            not seed_content
            or seed.global_chunk_order is None
            or seed.chunk_role == "child"
        ):
            return result
        if existing_context and len(existing_context) > len(seed_content):
            return result

        if not heading_path:
            radius = max(int(scan_radius), 1)
            stmt = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.kb_id,
                    DocumentChunk.material_id,
                    DocumentChunk.raw_text,
                    DocumentChunk.locator,
                    DocumentChunk.chunk_index,
                    DocumentChunk.heading_path,
                    DocumentChunk.global_chunk_order,
                )
                .where(
                    DocumentChunk.kb_id == seed.kb_id,
                    DocumentChunk.material_id == seed.material_id,
                    DocumentChunk.global_chunk_order >= int(seed.global_chunk_order) - radius,
                    DocumentChunk.global_chunk_order <= int(seed.global_chunk_order),
                )
                .order_by(DocumentChunk.global_chunk_order.asc())
            )

            rows = await self._run_with_timeout(self._db_execute(stmt), timeout_seconds)
            ordered_rows = [
                row
                for row in rows.all()
                if isinstance(getattr(row, "global_chunk_order", None), int)
            ]
            if not ordered_rows:
                return result

            seed_index = next(
                (
                    index
                    for index, row in enumerate(ordered_rows)
                    if int(row.global_chunk_order) == int(seed.global_chunk_order)
                ),
                None,
            )
            if seed_index is None or seed_index <= 0:
                return result

            start_index: int | None = None
            start_match: re.Match[str] | None = None
            for index in range(seed_index - 1, -1, -1):
                match = self._first_markdown_heading_match(
                    str(getattr(ordered_rows[index], "raw_text", "") or "")
                )
                if match is not None:
                    start_index = index
                    start_match = match
                    break
            if start_index is None or start_match is None:
                return result

            section_parts: list[str] = []
            for index in range(start_index, seed_index + 1):
                text = str(getattr(ordered_rows[index], "raw_text", "") or "")
                if index == start_index and start_match.start() > 0:
                    text = text[start_match.start() :]
                if index == seed_index:
                    end_match = self._first_markdown_heading_match(text)
                    if end_match is not None and end_match.start() > 0:
                        text = text[: end_match.start()]
                text = text.strip()
                if text:
                    section_parts.append(text)

            merged_section = "\n\n".join(section_parts).strip()
            if (
                not merged_section
                or merged_section == seed_content
                or seed_content not in merged_section
            ):
                return result

            result.context_text = merged_section
            return result

        radius = max(int(scan_radius), 1)
        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.kb_id,
                DocumentChunk.material_id,
                DocumentChunk.raw_text,
                DocumentChunk.locator,
                DocumentChunk.chunk_index,
                DocumentChunk.heading_path,
                DocumentChunk.global_chunk_order,
            )
            .where(
                DocumentChunk.kb_id == seed.kb_id,
                DocumentChunk.material_id == seed.material_id,
                DocumentChunk.global_chunk_order >= int(seed.global_chunk_order) - radius,
                DocumentChunk.global_chunk_order <= int(seed.global_chunk_order) + radius,
            )
            .order_by(DocumentChunk.global_chunk_order.asc())
        )

        rows = await self._run_with_timeout(self._db_execute(stmt), timeout_seconds)
        ordered_rows = [
            row
            for row in rows.all()
            if isinstance(getattr(row, "global_chunk_order", None), int)
        ]
        if not ordered_rows:
            return result

        seed_index = next(
            (
                index
                for index, row in enumerate(ordered_rows)
                if int(row.global_chunk_order) == int(seed.global_chunk_order)
            ),
            None,
        )
        if seed_index is None:
            return result

        def _same_heading_path(row: Any) -> bool:
            return str(getattr(row, "heading_path", "") or "").strip() == heading_path

        start = seed_index
        while start > 0 and _same_heading_path(ordered_rows[start - 1]):
            start -= 1
        end = seed_index
        while end + 1 < len(ordered_rows) and _same_heading_path(ordered_rows[end + 1]):
            end += 1

        section_parts = [
            str(getattr(row, "raw_text", "") or "").strip()
            for row in ordered_rows[start : end + 1]
            if str(getattr(row, "raw_text", "") or "").strip()
        ]
        if not section_parts:
            return result

        merged_section = "\n\n".join(section_parts).strip()
        if not merged_section or merged_section == seed_content:
            return result

        result.context_text = merged_section
        return result

    def _cache_key(
        self, query: str, kb_ids: list[uuid.UUID], top_k: int, strategy: dict
    ) -> str:
        """Build the retrieval cache key."""
        kb_str = ",".join(sorted(str(k) for k in kb_ids))
        fingerprint = json.dumps(strategy, sort_keys=True, ensure_ascii=False)
        raw = f"retrieval:{query}:{kb_str}:{top_k}:{fingerprint}"
        return f"retrieval:{hashlib.md5(raw.encode()).hexdigest()}"

    def _embedding_cache_key(self, query: str) -> str:
        """Build the embedding cache key."""
        return f"embedding:{hashlib.md5(query.encode()).hexdigest()}"

    def _rewrite_cache_key(self, query: str) -> str:
        """Build the query rewrite cache key."""
        return f"rewrite:{hashlib.md5(query.encode()).hexdigest()}"

    def _strategy_fingerprint(
        self,
        top_k: int,
        *,
        feature_flags: RetrievalFeatureFlags,
        runtime_overrides: RetrievalRuntimeOverrides,
        kb_fingerprint: dict[str, dict] | None = None,
    ) -> dict:
        """Build a stable strategy fingerprint used by retrieval cache keys."""
        fingerprint = {
            "top_k": top_k,
            "min_score": self._settings.retrieval_min_score,
            "raw_min_score": self._settings.retrieval_raw_min_score,
            "rank_fusion_min_score": self._settings.retrieval_rank_fusion_min_score,
            "rerank_min_score": self._settings.retrieval_rerank_min_score,
            "hybrid_enabled": feature_flags.hybrid_enabled,
            "hybrid_rrf_k": runtime_overrides.hybrid_rrf_k,
            "rewrite_enabled": feature_flags.query_rewrite_enabled,
            "rerank_enabled": feature_flags.rerank_enabled,
            "rerank_model": self._settings.retrieval_rerank_model,
            "retrieval_rerank_top_k": runtime_overrides.retrieval_rerank_top_k,
            "parent_max_parents": runtime_overrides.parent_max_parents,
            "parent_max_children_per_parent": runtime_overrides.parent_max_children_per_parent,
            "multiscale_per_window_top_k": runtime_overrides.multiscale_per_window_top_k,
            "multiscale_rrf_k": runtime_overrides.multiscale_rrf_k,
            "multiscale_max_documents": runtime_overrides.multiscale_max_documents,
            "multiscale_max_chunks_per_document": runtime_overrides.multiscale_max_chunks_per_document,
            "embedding_model": self._settings.embedding_model,
        }
        if kb_fingerprint:
            fingerprint["kb_retrieval"] = kb_fingerprint
        return fingerprint

    def _resolve_feature_flags(
        self,
        feature_overrides: dict[str, object] | None,
    ) -> RetrievalFeatureFlags:
        del feature_overrides
        return RetrievalFeatureFlags(
            query_rewrite_enabled=True,
            hybrid_enabled=True,
            rerank_enabled=True,
        )

    def _resolve_runtime_overrides(
        self, feature_overrides: dict[str, object] | None
    ) -> RetrievalRuntimeOverrides:
        hybrid_rrf_k = int(self._settings.retrieval_hybrid_rrf_k)
        retrieval_top_k = int(self._settings.retrieval_default_top_k)
        retrieval_rerank_top_k = int(self._settings.retrieval_max_top_k)

        parent_max_parents = 8
        parent_max_children_per_parent = 3
        multiscale_per_window_top_k = 40
        multiscale_rrf_k = 60
        multiscale_max_documents = 12
        multiscale_max_chunks_per_document = 2

        if isinstance(feature_overrides, dict):
            override_rrf_k = feature_overrides.get("hybrid_rrf_k")
            if isinstance(override_rrf_k, int):
                hybrid_rrf_k = override_rrf_k

            override_top_k = feature_overrides.get("retrieval_top_k")
            if isinstance(override_top_k, int):
                retrieval_top_k = override_top_k

            override_rerank_top_k = feature_overrides.get("retrieval_rerank_top_k")
            if isinstance(override_rerank_top_k, int):
                retrieval_rerank_top_k = override_rerank_top_k

            override_parent_max = feature_overrides.get("parent_max_parents")
            if isinstance(override_parent_max, int):
                parent_max_parents = override_parent_max

            override_parent_children = feature_overrides.get(
                "parent_max_children_per_parent"
            )
            if isinstance(override_parent_children, int):
                parent_max_children_per_parent = override_parent_children

            override_multiscale_per_window_top_k = feature_overrides.get(
                "multiscale_per_window_top_k"
            )
            if isinstance(override_multiscale_per_window_top_k, int):
                multiscale_per_window_top_k = override_multiscale_per_window_top_k

            override_multiscale_rrf_k = feature_overrides.get("multiscale_rrf_k")
            if isinstance(override_multiscale_rrf_k, int):
                multiscale_rrf_k = override_multiscale_rrf_k

            override_multiscale_max_documents = feature_overrides.get(
                "multiscale_max_documents"
            )
            if isinstance(override_multiscale_max_documents, int):
                multiscale_max_documents = override_multiscale_max_documents

            override_multiscale_max_chunks_per_document = feature_overrides.get(
                "multiscale_max_chunks_per_document"
            )
            if isinstance(override_multiscale_max_chunks_per_document, int):
                multiscale_max_chunks_per_document = (
                    override_multiscale_max_chunks_per_document
                )

        return RetrievalRuntimeOverrides(
            hybrid_rrf_k=max(1, min(int(hybrid_rrf_k), 200)),
            retrieval_top_k=max(1, int(retrieval_top_k)),
            retrieval_rerank_top_k=max(1, int(retrieval_rerank_top_k)),
            parent_max_parents=max(1, min(int(parent_max_parents), 20)),
            parent_max_children_per_parent=max(
                1, min(int(parent_max_children_per_parent), 10)
            ),
            multiscale_per_window_top_k=max(
                1, min(int(multiscale_per_window_top_k), 200)
            ),
            multiscale_rrf_k=max(1, min(int(multiscale_rrf_k), 200)),
            multiscale_max_documents=max(1, min(int(multiscale_max_documents), 100)),
            multiscale_max_chunks_per_document=max(
                1, min(int(multiscale_max_chunks_per_document), 20)
            ),
        )

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a <= 0 or norm_b <= 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    @staticmethod
    def _candidate_text_for_similarity(result: RetrievalResult) -> str:
        text = RetrievalService._result_text(result)
        if not text:
            return ""
        # Keep cost bounded while preserving enough semantics for similarity scoring.
        return text[:1200]

    @staticmethod
    def _result_text(result: RetrievalResult) -> str:
        context_text = (result.context_text or "").strip()
        if context_text:
            return context_text
        return (result.chunk.content or "").strip()

    @staticmethod
    def _result_excerpt_limit(result: RetrievalResult) -> int:
        context_text = (result.context_text or "").strip()
        chunk_text = (result.chunk.content or "").strip()
        if context_text and len(context_text) > len(chunk_text):
            return EXPANDED_RESULT_EXCERPT_MAX_CHARS
        return DEFAULT_RESULT_EXCERPT_MAX_CHARS

    @classmethod
    def _result_excerpt(cls, result: RetrievalResult) -> str:
        text = cls._result_text(result)
        if not text:
            return ""
        return text[: cls._result_excerpt_limit(result)]

    @classmethod
    def _candidate_text_for_dedup(cls, result: RetrievalResult) -> str:
        return cls._candidate_text_for_similarity(result)

    @staticmethod
    def _normalize_text_for_hash(text: str) -> str:
        return " ".join(text.strip().lower().split())

    @classmethod
    def _content_hash_for_result(cls, result: RetrievalResult) -> str | None:
        text = cls._candidate_text_for_dedup(result)
        if not text:
            return None
        normalized = cls._normalize_text_for_hash(text)
        if not normalized:
            return None
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _dedupe_by_chunk_identity(
        self,
        candidates: list[RetrievalResult],
    ) -> tuple[list[RetrievalResult], int]:
        best_by_key: dict[tuple[str, str, str], RetrievalResult] = {}
        order: list[tuple[str, str, str]] = []
        for item in candidates:
            key = self._candidate_key(item.chunk)
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = item
                order.append(key)
                continue
            if float(item.score) > float(existing.score):
                best_by_key[key] = item

        deduped = [best_by_key[key] for key in order if key in best_by_key]
        return deduped, max(0, len(candidates) - len(deduped))

    def _dedupe_by_content_hash(
        self,
        candidates: list[RetrievalResult],
    ) -> tuple[list[RetrievalResult], int]:
        best_by_hash: dict[str, tuple[int, RetrievalResult]] = {}
        passthrough: list[tuple[int, RetrievalResult]] = []

        for idx, item in enumerate(candidates):
            content_hash = self._content_hash_for_result(item)
            if content_hash is None:
                passthrough.append((idx, item))
                continue
            existing = best_by_hash.get(content_hash)
            if existing is None:
                best_by_hash[content_hash] = (idx, item)
                continue
            first_idx, existing_item = existing
            if float(item.score) > float(existing_item.score):
                best_by_hash[content_hash] = (first_idx, item)

        ordered = [
            *passthrough,
            *[(first_idx, item) for first_idx, item in best_by_hash.values()],
        ]
        ordered.sort(key=lambda pair: pair[0])
        deduped = [item for _, item in ordered]
        return deduped, max(0, len(candidates) - len(deduped))

    async def _dedupe_by_semantic_similarity(
        self,
        candidates: list[RetrievalResult],
        *,
        similarity_threshold: float,
        timeout_seconds: float | None = None,
    ) -> tuple[list[RetrievalResult], int, str]:
        if len(candidates) <= 1:
            return candidates, 0, "insufficient_candidates"

        texts = [self._candidate_text_for_dedup(item) for item in candidates]
        if not any(texts):
            return candidates, 0, "empty_candidate_text"
        embed_texts = [text if text else "content unavailable" for text in texts]

        timeout_value = float(self._settings.embedding_timeout_seconds)
        if timeout_seconds is not None:
            timeout_value = min(timeout_value, float(timeout_seconds))
        if timeout_value <= 0:
            raise asyncio.TimeoutError()

        vectors = await self._run_with_timeout(
            self._embedding.embed(
                texts=embed_texts,
                timeout_seconds=timeout_value,
                stage="dedupe",
            ),
            timeout_value,
        )
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(candidates)
            or not vectors
        ):
            return candidates, 0, "embedding_shape_mismatch"

        kept: list[int] = []
        ranked_indices = sorted(
            range(len(candidates)),
            key=lambda idx: (-float(candidates[idx].score), idx),
        )
        for idx in ranked_indices:
            vector = vectors[idx]
            if not isinstance(vector, list) or not vector:
                continue
            is_duplicate = False
            for kept_idx in kept:
                other_vector = vectors[kept_idx]
                if not isinstance(other_vector, list) or not other_vector:
                    continue
                if (
                    self._cosine_similarity(
                        cast(list[float], vector), cast(list[float], other_vector)
                    )
                    > similarity_threshold
                ):
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(idx)

        deduped_indices = sorted(kept)
        if not deduped_indices:
            return candidates, 0, "embedding_invalid_vectors"
        deduped = [candidates[idx] for idx in deduped_indices]
        removed = max(0, len(candidates) - len(deduped))
        return deduped, removed, "embedding_similarity"

    def _normalize_query(self, query: str) -> str:
        """Normalize the input query before retrieval."""
        normalized = " ".join(query.strip().split())
        if self._settings.retrieval_query_lowercase:
            normalized = normalized.lower()
        return normalized

    async def _get_query_embedding(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
        stage: str = "query_main",
    ) -> list[float]:
        """Get query embedding with cache support."""
        if self._redis and self._settings.retrieval_cache_enabled:
            cache_key = self._embedding_cache_key(query)
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding cache read failed; skip cache.", extra={"error": str(exc)}
                )
                cached = None
            if cached:
                logger.debug("Embedding cache hit", extra={"query": query[:50]})
                return json.loads(cached)

        timeout_value = float(self._settings.embedding_timeout_seconds)
        if timeout_seconds is not None:
            timeout_value = min(timeout_value, float(timeout_seconds))
        if timeout_value <= 0:
            raise asyncio.TimeoutError()

        start_time = time.perf_counter()
        embeddings = await self._run_with_timeout(
            self._embedding.embed(
                texts=[query],
                timeout_seconds=timeout_value,
                stage=stage,
            ),
            timeout_value,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "Embedding generated",
            extra={"query": query[:50], "latency_ms": latency_ms},
        )

        # Embeddings are reusable across rewrite/retrieval variants, so keep them slightly
        # longer than the short-lived retrieval result cache.
        if self._redis and self._settings.retrieval_cache_enabled:
            try:
                await self._redis.set(
                    self._embedding_cache_key(query),
                    json.dumps(embeddings[0]),
                    ex=self._settings.retrieval_cache_ttl_seconds * 2,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding cache write failed; skip cache.", extra={"error": str(exc)}
                )

        return embeddings[0]

    @staticmethod
    def _mean_embedding(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            raise ValueError("empty_vectors")
        dim = len(vectors[0])
        if dim == 0:
            raise ValueError("empty_vector")
        if any(len(vec) != dim for vec in vectors):
            raise ValueError("embedding_dim_mismatch")
        sums = [0.0] * dim
        for vec in vectors:
            for idx, value in enumerate(vec):
                sums[idx] += float(value)
        count = float(len(vectors))
        return [value / count for value in sums]

    async def _resolve_query_embedding(
        self,
        item: QueryItem,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[list[float], int, int, str]:
        """Resolve a query embedding, with HyDE batch aggregation when present."""
        query = str(item.get("query") or "").strip()
        if not query:
            raise ValueError("empty_query")

        query_stage = self._query_embedding_stage(item)

        if str(item.get("kind") or "") != "hyde":
            embedding = await self._get_query_embedding(
                query,
                timeout_seconds=timeout_seconds,
                stage=query_stage,
            )
            return embedding, 0, 0, "not_hyde"

        raw_hyde_queries = item.get("hyde_queries")
        hyde_queries: list[str] = []
        if isinstance(raw_hyde_queries, list):
            for value in raw_hyde_queries:
                if not isinstance(value, str):
                    continue
                normalized = " ".join(value.strip().split())
                if normalized and normalized not in hyde_queries:
                    hyde_queries.append(normalized)
                if len(hyde_queries) >= HYDE_NUM_HYPOTHESES:
                    break
        if not hyde_queries:
            hyde_queries = [query]

        aggregation = (
            str(item.get("hyde_aggregation") or "").strip().lower() or HYDE_AGGREGATION
        )
        if aggregation != HYDE_AGGREGATION:
            embedding = await self._get_query_embedding(
                hyde_queries[0],
                timeout_seconds=timeout_seconds,
                stage="hyde",
            )
            return embedding, len(hyde_queries), 1, "unsupported_aggregation"
        if len(hyde_queries) == 1:
            embedding = await self._get_query_embedding(
                hyde_queries[0],
                timeout_seconds=timeout_seconds,
                stage="hyde",
            )
            return embedding, len(hyde_queries), 1, "single_sample"

        deadline = self._make_deadline(timeout_seconds)
        vectors: list[list[float]] = []
        for hyde_query in hyde_queries:
            remaining = self._remaining_seconds(deadline)
            if remaining is not None and remaining <= 0:
                raise asyncio.TimeoutError()
            vec = await self._get_query_embedding(
                hyde_query,
                timeout_seconds=remaining,
                stage="hyde",
            )
            vectors.append(vec)

        try:
            merged = self._mean_embedding(vectors)
        except ValueError:
            # Degrade gracefully to the first usable sample.
            return vectors[0], len(hyde_queries), 1, "dim_mismatch_first_sample"
        return merged, len(hyde_queries), len(vectors), "none"

    async def _maybe_rewrite_query(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> RewriteResult:
        """Optionally rewrite query."""
        rewrite_enabled = True if enabled is None else bool(enabled)
        if not rewrite_enabled:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="disabled",
                latency_ms=0,
            )

        cache_key = self._rewrite_cache_key(query)
        if self._redis and self._settings.retrieval_cache_enabled:
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Rewrite cache read failed; continue rewrite flow.", extra={"error": str(exc)}
                )
            if cached:
                return RewriteResult(
                    query=cached,
                    rewritten=cached.strip() != query,
                    reason="cache_hit",
                    latency_ms=0,
                )

        rewriter = self._query_rewriter or QueryRewriteService(self._settings)
        self._query_rewriter = rewriter
        result = await rewriter.rewrite(query)

        if self._redis and self._settings.retrieval_cache_enabled and result.query:
            try:
                await self._redis.set(
                    cache_key,
                    result.query,
                    ex=self._settings.retrieval_cache_ttl_seconds,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Rewrite cache write failed; skip cache.", extra={"error": str(exc)}
                )

        return result

    @staticmethod
    def _candidate_key(chunk: RetrievedChunk) -> tuple[str, str, str]:
        # Keep a stable, explicit key for global dedupe across KBs/materials.
        return (str(chunk.kb_id), str(chunk.material_id), str(chunk.id))

    @staticmethod
    def _query_hit_source(item: QueryItem) -> QueryHitSource:
        src: QueryHitSource = {
            "kind": item.get("kind", "other"),  # type: ignore[typeddict-item]
            "query": item.get("query", ""),  # type: ignore[typeddict-item]
        }
        if "index" in item:
            src["index"] = int(item["index"])  # type: ignore[typeddict-item]
        if "note" in item and item.get("note"):
            src["note"] = str(item["note"])  # type: ignore[typeddict-item]
        return src

    @staticmethod
    def _add_hit_source(hits: list[QueryHitSource], src: QueryHitSource) -> None:
        key = (src.get("kind"), src.get("query"), src.get("index"), src.get("note"))
        for existing in hits:
            ek = (
                existing.get("kind"),
                existing.get("query"),
                existing.get("index"),
                existing.get("note"),
            )
            if ek == key:
                return
        hits.append(src)

    @staticmethod
    def _query_embedding_stage(item: QueryItem) -> str:
        kind = str(item.get("kind") or "").strip().lower()
        if kind == "hyde":
            return "hyde"
        if kind == "main":
            return "query_main"
        return "query_variant"

    @staticmethod
    def _embedding_failure_reason(
        exc: Exception,
        *,
        fallback_stage: str,
    ) -> str:
        if isinstance(exc, EmbeddingCallError):
            stage = str(exc.stage or fallback_stage)
            if exc.breaker_state == "open" or getattr(exc, "short_circuited", False):
                return f"{stage}:breaker_open"
            if exc.status_code is not None:
                return f"{stage}:status_{exc.status_code}"
            if exc.retryable:
                return f"{stage}:retryable_error"
            return f"{stage}:error"
        if isinstance(exc, asyncio.TimeoutError):
            return f"{fallback_stage}:timeout"
        return f"{fallback_stage}:error"

    @staticmethod
    def _rrf_rank(
        ranked_lists: list[list[tuple[str, str, str]]],
        *,
        k: int,
    ) -> tuple[list[tuple[str, str, str]], dict[tuple[str, str, str], float]]:
        """Reciprocal Rank Fusion (RRF).

        Returns (ordered_keys, score_by_key).
        """

        scores: dict[tuple[str, str, str], float] = {}
        best_rank: dict[tuple[str, str, str], int] = {}
        for lst in ranked_lists:
            for rank, key in enumerate(lst, start=1):
                scores[key] = scores.get(key, 0.0) + 1.0 / float(k + rank)
                best_rank[key] = min(best_rank.get(key, rank), rank)

        ordered = sorted(
            scores.keys(),
            key=lambda key: (-scores[key], best_rank.get(key, 10**9), key),
        )
        return ordered, scores

    @staticmethod
    def _build_multiscale_window_collections(
        configs: dict[uuid.UUID, IndexConfig],
        *,
        base_collection: str,
    ) -> list[str]:
        names: set[str] = set()
        for cfg in configs.values():
            if cfg.chunking.general_strategy != ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                continue
            for window in cfg.chunking.query_dependent_multiscale.windows:
                names.add(
                    collection_name_for_window(
                        base_collection,
                        window.chunk_size_tokens,
                        window.chunk_overlap_tokens,
                    )
                )
        return sorted(names)

    @staticmethod
    def _split_kb_ids_by_strategy(
        kb_ids: list[uuid.UUID],
        configs: dict[uuid.UUID, IndexConfig],
    ) -> tuple[list[str], list[str]]:
        default_kb_ids: list[str] = []
        multiscale_kb_ids: list[str] = []
        for kb_id in kb_ids:
            cfg = configs.get(kb_id)
            if cfg is None:
                default_kb_ids.append(str(kb_id))
                continue
            if cfg.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                multiscale_kb_ids.append(str(kb_id))
            else:
                default_kb_ids.append(str(kb_id))
        return default_kb_ids, multiscale_kb_ids

    async def retrieve_layer(
        self,
        *,
        query_items: list[QueryItem],
        kb_ids: list[uuid.UUID],
        top_n: int,
        per_query_top_k: int | None = None,
        global_candidates_limit: int | None = None,
        rerank_input_limit: int | None = None,
        extra_filter_expr: str | None = None,
        timeout_seconds: float | None = None,
        feature_overrides: dict[str, object] | None = None,
    ) -> RetrievalLayerDraft:
        """Unified RetrievalLayer: native hybrid_search + global RRF + optional rerank + Top-N.

        NOTE: Any retry/transform query loop should come back to THIS method to ensure
        the retrieval chain stays consistent (hybrid_search+RRF+optional rerank).
        """

        deadline = self._make_deadline(timeout_seconds)
        if deadline is not None and float(timeout_seconds) <= 0:
            draft = self._empty_layer_draft(reason="timeout")
            self._last_layer_draft = draft
            return draft

        if not kb_ids or not query_items:
            draft = self._empty_layer_draft()
            self._last_layer_draft = draft
            return draft

        feature_flags = self._resolve_feature_flags(feature_overrides)
        runtime_overrides = self._resolve_runtime_overrides(feature_overrides)

        def _timeout_draft() -> RetrievalLayerDraft:
            draft = self._empty_layer_draft(reason="timeout")
            self._last_layer_draft = draft
            return draft

        # Enforce reasonable caps (production guardrails).
        if top_n <= 0:
            top_n = runtime_overrides.retrieval_top_k
        top_n = min(int(top_n), int(self._settings.retrieval_max_top_k))
        per_query_top_k = (
            int(per_query_top_k)
            if per_query_top_k is not None
            else int(runtime_overrides.retrieval_top_k)
        )
        per_query_top_k = max(
            1, min(per_query_top_k, int(self._settings.retrieval_max_top_k))
        )

        query_count = max(1, len(query_items))
        max_candidate_cap = max(
            int(self._settings.retrieval_max_top_k),
            int(self._settings.retrieval_max_top_k) * max(2, query_count * 2),
        )
        if global_candidates_limit is None:
            # Worst-case: one hybrid result set per query, plus extra headroom for fanout.
            global_candidates_limit = min(
                max_candidate_cap,
                per_query_top_k * query_count,
            )
        global_candidates_limit = max(int(global_candidates_limit), top_n)
        global_candidates_limit = min(global_candidates_limit, max_candidate_cap)

        if rerank_input_limit is None:
            rerank_input_limit = runtime_overrides.retrieval_rerank_top_k
        rerank_input_limit = max(int(rerank_input_limit), top_n)
        rerank_input_limit = min(rerank_input_limit, global_candidates_limit)

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            kb_configs = await self._run_with_timeout(
                self._load_kb_index_configs(kb_ids), timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        default_kb_id_strs, multiscale_kb_id_strs = self._split_kb_ids_by_strategy(
            kb_ids, kb_configs
        )
        multiscale_collections = self._build_multiscale_window_collections(
            kb_configs,
            base_collection=self._settings.milvus_collection,
        )

        rrf_k = int(runtime_overrides.hybrid_rrf_k)

        chunk_by_key: dict[tuple[str, str, str], RetrievedChunk] = {}
        hits_by_key: dict[tuple[str, str, str], list[QueryHitSource]] = {}
        per_query_ranked: list[list[tuple[str, str, str]]] = []

        hybrid_hits_total = 0
        hyde_requested_total = 0
        hyde_used_total = 0
        hyde_aggregation_reason = "not_used"
        optional_embedding_skips: list[str] = []

        # Use the "main" query as rerank query, fallback to the first available.
        main_query = ""
        for item in query_items:
            if item.get("kind") == "main" and (item.get("query") or "").strip():
                main_query = str(item.get("query") or "")
                break
        if not main_query:
            main_query = str(query_items[0].get("query") or "")
        hyde_retry_regenerated = any(
            str(item.get("kind") or "") == "hyde"
            and str(item.get("note") or "") == "retry_regenerated"
            for item in query_items
        )

        async def _process_query_item(
            index: int,
            item: QueryItem,
        ) -> tuple[
            int,
            int,
            dict[tuple[str, str, str], RetrievedChunk],
            dict[tuple[str, str, str], list[QueryHitSource]],
            list[tuple[str, str, str]],
            int,
            int,
            str,
            list[str],
        ]:
            q = (item.get("query") or "").strip()
            if not q:
                return index, 0, {}, {}, [], 0, 0, "empty_query", []

            if deadline is not None:
                remaining = self._remaining_seconds(deadline)
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError()

            use_dense = bool(item.get("use_dense", True))
            use_bm25 = bool(item.get("use_bm25", True)) and feature_flags.hybrid_enabled
            if not feature_flags.hybrid_enabled or not use_dense or not use_bm25:
                return index, 0, {}, {}, [], 0, 0, "hybrid_disabled", []

            hyde_requested_count = 0
            hyde_used_count = 0
            hyde_reason = "not_hyde"
            local_optional_embedding_skips: list[str] = []
            src = self._query_hit_source(item)
            local_chunk_by_key: dict[tuple[str, str, str], RetrievedChunk] = {}
            local_hits_by_key: dict[tuple[str, str, str], list[QueryHitSource]] = {}

            def _build_query_result(
                retrieval_hits: list[object],
                *,
                hit_count: int,
            ) -> tuple[
                int,
                int,
                dict[tuple[str, str, str], RetrievedChunk],
                dict[tuple[str, str, str], list[QueryHitSource]],
                list[tuple[str, str, str]],
                int,
                int,
                str,
                list[str],
            ]:
                ranked_keys: list[tuple[str, str, str]] = []
                for hit in retrieval_hits:
                    chunk = self._build_chunk_from_hit(hit)
                    if not chunk:
                        continue
                    key = self._candidate_key(chunk)
                    local_chunk_by_key.setdefault(key, chunk)
                    local_hits_by_key.setdefault(key, [])
                    self._add_hit_source(local_hits_by_key[key], src)
                    ranked_keys.append(key)

                if ranked_keys:
                    ranked_keys = list(dict.fromkeys(ranked_keys))

                return (
                    index,
                    hit_count,
                    local_chunk_by_key,
                    local_hits_by_key,
                    ranked_keys,
                    hyde_requested_count,
                    hyde_used_count,
                    hyde_reason,
                    local_optional_embedding_skips,
                )

            async def _safe_sparse(
                *,
                kb_id_values: list[str],
                collection_name: str | None = None,
            ) -> list[dict]:
                if not kb_id_values:
                    return []
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    return await self._run_with_timeout(
                        self._milvus.sparse_search(
                            query=q,
                            kb_ids=kb_id_values,
                            top_k=per_query_top_k,
                            extra_filter_expr=extra_filter_expr,
                            collection_name=collection_name,
                        ),
                        timeout_value,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Sparse retrieval timed out.", extra={"query": q[:50]}
                    )
                    return []
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Sparse retrieval failed.", extra={"error": str(exc)}
                    )
                    return []

            async def _run_sparse_fallback(reason: str) -> tuple[
                int,
                int,
                dict[tuple[str, str, str], RetrievedChunk],
                dict[tuple[str, str, str], list[QueryHitSource]],
                list[tuple[str, str, str]],
                int,
                int,
                str,
                list[str],
            ]:
                local_optional_embedding_skips.append(f"{reason}->sparse_only")
                sparse_hits: list[dict] = []
                sparse_hits.extend(await _safe_sparse(kb_id_values=default_kb_id_strs))
                if multiscale_kb_id_strs:
                    for collection_name in multiscale_collections:
                        sparse_hits.extend(
                            await _safe_sparse(
                                kb_id_values=multiscale_kb_id_strs,
                                collection_name=collection_name,
                            )
                        )
                return _build_query_result(sparse_hits, hit_count=len(sparse_hits))
            try:
                remaining = self._remaining_seconds(deadline)
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError()
                (
                    embedding,
                    hyde_requested_count,
                    hyde_used_count,
                    hyde_reason,
                ) = await self._resolve_query_embedding(
                    item,
                    timeout_seconds=remaining,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Embedding request timed out; fallback to sparse retrieval for this query.",
                    extra={"query": q[:50]},
                )
                return await _run_sparse_fallback(
                    self._embedding_failure_reason(
                        asyncio.TimeoutError(),
                        fallback_stage=self._query_embedding_stage(item),
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding request failed; fallback to sparse retrieval for this query.",
                    extra={"error": str(exc)},
                )
                return await _run_sparse_fallback(
                    self._embedding_failure_reason(
                        exc,
                        fallback_stage=self._query_embedding_stage(item),
                    )
                )

            async def _safe_hybrid(
                *,
                kb_id_values: list[str],
                collection_name: str | None = None,
            ) -> list[dict]:
                if not kb_id_values:
                    return []
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    return await self._run_with_timeout(
                        self._milvus.hybrid_search(
                            embedding=embedding,
                            query=q,
                            kb_ids=kb_id_values,
                            top_k=per_query_top_k,
                            rrf_k=rrf_k,
                            extra_filter_expr=extra_filter_expr,
                            collection_name=collection_name,
                        ),
                        timeout_value,
                    )
                except asyncio.TimeoutError:
                    if deadline is not None:
                        raise
                    logger.warning(
                        "Hybrid retrieval timed out.", extra={"query": q[:50]}
                    )
                    return []
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Hybrid retrieval failed.", extra={"error": str(exc)}
                    )
                    return []

            hybrid_hits: list[dict] = []
            hybrid_hits.extend(
                await _safe_hybrid(kb_id_values=default_kb_id_strs)
            )
            if multiscale_kb_id_strs:
                for collection_name in multiscale_collections:
                    hybrid_hits.extend(
                        await _safe_hybrid(
                            kb_id_values=multiscale_kb_id_strs,
                            collection_name=collection_name,
                        )
                    )
            return _build_query_result(hybrid_hits, hit_count=len(hybrid_hits))

        semaphore = asyncio.Semaphore(QUERY_FANOUT_CONCURRENCY)

        async def _run_with_limit(
            index: int, item: QueryItem
        ) -> tuple[
            int,
            int,
            dict[tuple[str, str, str], RetrievedChunk],
            dict[tuple[str, str, str], list[QueryHitSource]],
            list[tuple[str, str, str]],
            int,
            int,
            str,
            list[str],
        ]:
            async with semaphore:
                return await _process_query_item(index, item)

        fanout_tasks = [
            asyncio.create_task(_run_with_limit(index, item))
            for index, item in enumerate(query_items)
        ]
        fanout_results = await asyncio.gather(*fanout_tasks, return_exceptions=True)
        for result in fanout_results:
            if isinstance(result, asyncio.TimeoutError):
                return _timeout_draft()
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                logger.warning(
                    "Query fanout branch failed.", extra={"error": str(result)}
                )

        for result in fanout_results:
            if isinstance(result, Exception):
                continue
            (
                _index,
                hybrid_count,
                local_chunk_by_key,
                local_hits_by_key,
                per_keys,
                hyde_requested_count,
                hyde_used_count,
                hyde_reason,
                local_optional_embedding_skips,
            ) = result
            hybrid_hits_total += hybrid_count
            hyde_requested_total += hyde_requested_count
            hyde_used_total += hyde_used_count
            if hyde_requested_count > 0:
                hyde_aggregation_reason = hyde_reason
            optional_embedding_skips.extend(local_optional_embedding_skips)

            for key, chunk in local_chunk_by_key.items():
                chunk_by_key.setdefault(key, chunk)
                hits_by_key.setdefault(key, [])
                for src in local_hits_by_key.get(key, []):
                    self._add_hit_source(hits_by_key[key], src)

            if per_keys:
                per_query_ranked.append(per_keys)

        if not per_query_ranked:
            draft = RetrievalLayerDraft(
                retrieval_candidates=[],
                reranked_candidates=[],
                evidence_items=[],
                results=[],
                stats={
                    "hybrid_hits": hybrid_hits_total,
                    "optional_embedding_skips": optional_embedding_skips,
                    "hyde_requested_count": hyde_requested_total,
                    "hyde_used_count": hyde_used_total,
                    "hyde_aggregation": (
                        HYDE_AGGREGATION if hyde_requested_total > 0 else None
                    ),
                    "hyde_embedding_fallback": (
                        hyde_aggregation_reason if hyde_requested_total > 0 else None
                    ),
                    "hyde_retry_regenerated": hyde_retry_regenerated,
                    "rrf_candidates": 0,
                    "rerank_applied": False,
                },
            )
            self._last_layer_draft = draft
            return draft

        global_keys, global_scores = self._rrf_rank(per_query_ranked, k=rrf_k)
        global_keys = global_keys[:global_candidates_limit]

        # Build RetrievalResult list in global RRF order.
        rrf_results: list[RetrievalResult] = []
        for key in global_keys:
            chunk = chunk_by_key.get(key)
            if chunk is None:
                continue
            rrf_results.append(
                RetrievalResult(chunk=chunk, score=global_scores.get(key, 0.0))
            )

        # Prefer Milvus output_fields; backfill from Postgres only when necessary.
        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            await self._run_with_timeout(
                self._hydrate_chunks_from_postgres([r.chunk for r in rrf_results]),
                timeout_value,
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            rrf_results = await self._expand_direct_section_neighbors(
                rrf_results,
                query_items=query_items,
                top_n=top_n,
                timeout_seconds=timeout_value,
                hits_by_key=hits_by_key,
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        # kb_configs has been loaded before retrieval loop for multiscale routing.
        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            rrf_results = await self._apply_parent_child_strategy(
                rrf_results,
                kb_configs,
                max_parents=runtime_overrides.parent_max_parents,
                max_children_per_parent=runtime_overrides.parent_max_children_per_parent,
                timeout_seconds=timeout_value,
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            rrf_results = await self._apply_query_dependent_multiscale_strategy(
                rrf_results,
                kb_configs,
                per_window_top_k=runtime_overrides.multiscale_per_window_top_k,
                rrf_k=runtime_overrides.multiscale_rrf_k,
                max_documents=runtime_overrides.multiscale_max_documents,
                max_chunks_per_document=runtime_overrides.multiscale_max_chunks_per_document,
                timeout_seconds=timeout_value,
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            await self._run_with_timeout(
                self._ensure_chunk_citation_labels([r.chunk for r in rrf_results]),
                timeout_value,
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        pre_min_score_count = len(rrf_results)
        rrf_results, rank_fusion_filtered_count = self._apply_stage_score_cutoff(
            rrf_results,
            stage="rank_fusion",
        )
        pre_dedup_count = len(rrf_results)

        rrf_results, dedup_exact_removed = self._dedupe_by_chunk_identity(rrf_results)
        rrf_results, dedup_hash_removed = self._dedupe_by_content_hash(rrf_results)
        dedup_similarity_removed = 0
        dedup_similarity_reason = "insufficient_candidates"
        if rrf_results:
            try:
                dedup_timeout = self._effective_timeout(
                    deadline=deadline, per_call_timeout=None
                )
                (
                    rrf_results,
                    dedup_similarity_removed,
                    dedup_similarity_reason,
                ) = await self._dedupe_by_semantic_similarity(
                    rrf_results,
                    similarity_threshold=DEDUP_EMBEDDING_SIMILARITY_THRESHOLD,
                    timeout_seconds=dedup_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Semantic-similarity dedupe timed out; skip this dedupe step.")
                dedup_similarity_reason = "dedupe:timeout"
                optional_embedding_skips.append(dedup_similarity_reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Semantic-similarity dedupe failed; keep original candidates.", extra={"error": str(exc)}
                )
                dedup_similarity_reason = self._embedding_failure_reason(
                    exc,
                    fallback_stage="dedupe",
                )
                optional_embedding_skips.append(dedup_similarity_reason)
        post_dedup_count = len(rrf_results)

        candidates_for_rerank = rrf_results[:rerank_input_limit]

        # Rerank: RRF -> rerank -> Top-N. Inputs are additionally capped.
        rerank_applied = False
        rerank_reason: str | None = "disabled"
        rerank_latency_ms: int | None = None
        rerank_filtered_count = 0
        final_results: list[RetrievalResult] = []

        if candidates_for_rerank and feature_flags.rerank_enabled:
            try:
                rerank_timeout = self._effective_timeout(
                    deadline=deadline, per_call_timeout=timeout_seconds
                )
                ordered, applied, reason, latency_ms = await self._maybe_rerank(
                    main_query,
                    candidates_for_rerank,
                    top_n,
                    timeout_seconds=rerank_timeout,
                    hard_timeout=False,
                    enabled=feature_flags.rerank_enabled,
                )
            except asyncio.TimeoutError:
                # Rerank is optional: degrade to RRF order when timeout happens.
                logger.warning("Rerank timed out; fallback to RRF order")
                ordered, applied, reason, latency_ms = (
                    candidates_for_rerank,
                    False,
                    "timeout",
                    None,
                )
            rerank_applied = applied
            rerank_reason = reason
            rerank_latency_ms = latency_ms
            candidate_results = (ordered if applied else candidates_for_rerank)[:top_n]
            if applied:
                candidate_results, rerank_filtered_count = self._apply_stage_score_cutoff(
                    candidate_results,
                    stage="rerank",
                )
            final_results = candidate_results
        else:
            final_results = candidates_for_rerank[:top_n]

        if final_results:
            try:
                for result in final_results:
                    timeout_value = self._effective_timeout(
                        deadline=deadline,
                        per_call_timeout=timeout_seconds,
                    )
                    await self._populate_result_context_from_heading_path(
                        result,
                        timeout_seconds=timeout_value,
                    )
            except asyncio.TimeoutError:
                logger.warning("Heading-path context enrichment timed out; keep original excerpts")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Heading-path context enrichment failed; keep original excerpts",
                    extra={"error": str(exc)},
                )

        # Build JSON-friendly drafts for agentic state / auditing.
        retrieval_candidates: list[dict] = []
        for r in rrf_results:
            key = self._candidate_key(r.chunk)
            retrieval_candidates.append(
                {
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "score": float(r.score),
                    "stage": "rrf",
                    "excerpt": self._result_excerpt(r),
                    "locator": r.chunk.locator,
                    "metadata": r.chunk.metadata,
                    "chunk_role": r.chunk.chunk_role,
                    "parent_chunk_id": r.chunk.parent_chunk_id,
                    "hits": hits_by_key.get(key, []),
                }
            )

        reranked_candidates: list[dict] = []
        for r in final_results:
            key = self._candidate_key(r.chunk)
            reranked_candidates.append(
                {
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "score": float(r.score),
                    "stage": "rerank" if rerank_applied else "rrf",
                    "excerpt": self._result_excerpt(r),
                    "locator": r.chunk.locator,
                    "metadata": r.chunk.metadata,
                    "chunk_role": r.chunk.chunk_role,
                    "parent_chunk_id": r.chunk.parent_chunk_id,
                    "hits": hits_by_key.get(key, []),
                }
            )

        evidence_items: list[dict] = []
        for r in final_results:
            key = self._candidate_key(r.chunk)
            evidence_items.append(
                {
                    "source_kind": "kb",
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "locator": r.chunk.locator,
                    "excerpt": self._result_excerpt(r),
                    "score": float(r.score),
                    "hits": hits_by_key.get(key, []),
                }
            )

        draft = RetrievalLayerDraft(
            retrieval_candidates=retrieval_candidates,
            reranked_candidates=reranked_candidates,
            evidence_items=evidence_items,
            results=final_results,
            stats={
                "hybrid_hits": hybrid_hits_total,
                "optional_embedding_skips": optional_embedding_skips,
                "hyde_requested_count": hyde_requested_total,
                "hyde_used_count": hyde_used_total,
                "hyde_aggregation": HYDE_AGGREGATION if hyde_requested_total > 0 else None,
                "hyde_embedding_fallback": (
                    hyde_aggregation_reason if hyde_requested_total > 0 else None
                ),
                "hyde_retry_regenerated": hyde_retry_regenerated,
                "pre_min_score_candidates": pre_min_score_count,
                "filtered_count": rank_fusion_filtered_count + rerank_filtered_count,
                "rank_fusion_filtered_count": rank_fusion_filtered_count,
                "rerank_filtered_count": rerank_filtered_count,
                "pre_dedup_candidates": pre_dedup_count,
                "post_dedup_candidates": post_dedup_count,
                "dedup_exact_removed": dedup_exact_removed,
                "dedup_hash_removed": dedup_hash_removed,
                "dedup_similarity_removed": dedup_similarity_removed,
                "dedup_similarity_reason": dedup_similarity_reason,
                "dedup_similarity_threshold": DEDUP_EMBEDDING_SIMILARITY_THRESHOLD,
                "rrf_candidates": len(rrf_results),
                "global_candidates_limit": global_candidates_limit,
                "rerank_input_limit": rerank_input_limit,
                "fanout_concurrency": QUERY_FANOUT_CONCURRENCY,
                "hybrid_enabled": feature_flags.hybrid_enabled,
                "hybrid_rrf_k": runtime_overrides.hybrid_rrf_k,
                "rerank_enabled": feature_flags.rerank_enabled,
                "rerank_applied": rerank_applied,
                "rerank_reason": rerank_reason,
                "rerank_latency_ms": rerank_latency_ms,
            },
        )
        self._last_layer_draft = draft
        return draft

    async def _maybe_rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int,
        *,
        timeout_seconds: float | None = None,
        hard_timeout: bool = False,
        enabled: bool | None = None,
    ) -> tuple[list[RetrievalResult], bool, str | None, int | None]:
        """Optionally rerank candidates and gracefully degrade on failures."""
        rerank_enabled = True if enabled is None else bool(enabled)
        if not rerank_enabled:
            return results, False, "disabled", None

        if not results:
            return results, False, "empty_candidates", None

        reranker = self._reranker or RerankClient(self._settings)
        self._reranker = reranker

        # Rerank is optional quality boost: stay within the configured soft budget and
        # gracefully degrade to the original ordering when the reranker is too slow.
        timeout_value = float(self._settings.retrieval_rerank_timeout_seconds)
        if timeout_seconds is not None:
            timeout_value = min(timeout_value, float(timeout_seconds))
        if timeout_value <= 0:
            return results, False, "budget_exhausted", None

        start_time = time.perf_counter()
        try:
            rerank_results = await self._run_with_timeout(
                reranker.rerank(
                    query=query,
                    documents=[self._result_text(r) for r in results],
                    top_n=min(top_k, len(results)),
                    timeout_seconds=timeout_value,
                ),
                timeout_value,
            )
        except asyncio.TimeoutError:
            if hard_timeout:
                raise
            logger.warning("Rerank timed out; fallback to original order.", extra={"timeout": timeout_value})
            return results, False, "timeout", None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Rerank failed; fallback to original order.", extra={"error": str(exc)})
            return results, False, "error", None
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        if not rerank_results:
            return results, False, "empty_results", latency_ms

        ordered, used = [], set()
        for item in rerank_results:
            if 0 <= item.index < len(results):
                ordered.append(
                    RetrievalResult(
                        chunk=results[item.index].chunk,
                        score=item.score,
                        context_text=results[item.index].context_text,
                    )
                )
                used.add(item.index)

        # Keep original ordering for items not returned by rerank.
        for idx, res in enumerate(results):
            if idx not in used:
                ordered.append(res)

        return ordered, True, None, latency_ms

    async def _load_kb_index_configs(
        self, kb_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, IndexConfig]:
        if not kb_ids or self._db is None:
            return {}

        configs: dict[uuid.UUID, IndexConfig] = {}
        snapshot_stmt = select(KBConfigSnapshot.kb_id, KBConfigSnapshot.config_json).where(
            KBConfigSnapshot.kb_id.in_(kb_ids),
            KBConfigSnapshot.is_active.is_(True),
        )
        snapshot_rows = await self._db_execute(snapshot_stmt)
        for kb_id, raw in snapshot_rows.all():
            try:
                configs[kb_id] = IndexConfig.model_validate(raw or {})
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Snapshot IndexConfig parse failed; fallback to knowledge_bases.index_config.",
                    extra={"kb_id": str(kb_id), "error": str(exc)},
                )

        missing_kb_ids = [kb_id for kb_id in kb_ids if kb_id not in configs]
        if missing_kb_ids:
            fallback_stmt = select(KnowledgeBase.id, KnowledgeBase.index_config).where(
                KnowledgeBase.id.in_(missing_kb_ids)
            )
            fallback_rows = await self._db_execute(fallback_stmt)
            for kb_id, raw in fallback_rows.all():
                try:
                    configs[kb_id] = IndexConfig.model_validate(raw or {})
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        "IndexConfig parse failed; fallback to defaults.",
                        extra={"kb_id": str(kb_id), "error": str(exc)},
                    )
        return configs

    @staticmethod
    def _build_kb_fingerprint(configs: dict[uuid.UUID, IndexConfig]) -> dict[str, dict]:
        if not configs:
            return {}
        fingerprint: dict[str, dict] = {}
        for kb_id, cfg in configs.items():
            item = {
                "general_strategy": cfg.chunking.general_strategy.value,
            }
            if cfg.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                item["query_dependent_multiscale"] = {
                    "windows": [
                        {
                            "chunk_size_tokens": window.chunk_size_tokens,
                            "chunk_overlap_tokens": window.chunk_overlap_tokens,
                        }
                        for window in cfg.chunking.query_dependent_multiscale.windows
                    ],
                }
            fingerprint[str(kb_id)] = item
        return dict(sorted(fingerprint.items(), key=lambda item: item[0]))

    @staticmethod
    def _build_chunk_from_hit(hit) -> RetrievedChunk | None:
        chunk_id = getattr(hit, "chunk_id", None)
        kb_id = getattr(hit, "kb_id", None)
        material_id = getattr(hit, "material_id", None)
        if not chunk_id or not kb_id or not material_id:
            return None
        try:
            return RetrievedChunk(
                id=uuid.UUID(str(chunk_id)),
                kb_id=uuid.UUID(str(kb_id)),
                material_id=uuid.UUID(str(material_id)),
                content=getattr(hit, "content", "") or "",
                context=getattr(hit, "context", None),
                locator=getattr(hit, "locator", None),
                metadata=getattr(hit, "metadata", None),
                chunk_role=getattr(hit, "chunk_role", None),
                parent_chunk_id=getattr(hit, "parent_chunk_id", None),
                child_seq=getattr(hit, "child_seq", None),
                chunk_index=getattr(hit, "chunk_index", None),
                heading_path=getattr(hit, "heading_path", None),
                global_chunk_order=getattr(hit, "global_chunk_order", None),
            )
        except Exception:
            return None

    @staticmethod
    def _build_chunk_from_record(record: dict) -> RetrievedChunk | None:
        chunk_id = record.get("chunk_id")
        kb_id = record.get("kb_id")
        material_id = record.get("material_id")
        if not chunk_id or not kb_id or not material_id:
            return None
        try:
            return RetrievedChunk(
                id=uuid.UUID(str(chunk_id)),
                kb_id=uuid.UUID(str(kb_id)),
                material_id=uuid.UUID(str(material_id)),
                content=record.get("content") or "",
                context=record.get("context"),
                locator=record.get("locator"),
                metadata=record.get("metadata"),
                chunk_role=record.get("chunk_role"),
                parent_chunk_id=record.get("parent_chunk_id"),
                child_seq=record.get("child_seq"),
                chunk_index=record.get("chunk_index"),
                heading_path=record.get("heading_path"),
                global_chunk_order=record.get("global_chunk_order"),
            )
        except Exception:
            return None

    async def _apply_parent_child_strategy(
        self,
        results: list[RetrievalResult],
        kb_configs: dict[uuid.UUID, IndexConfig],
        *,
        max_parents: int,
        max_children_per_parent: int,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        if not results or not kb_configs:
            for r in results:
                if not r.context_text:
                    r.context_text = r.chunk.content
            return results
        if timeout_seconds is not None and float(timeout_seconds) <= 0:
            raise asyncio.TimeoutError()

        parent_ids: set[str] = set()
        selected_child_ids: set[uuid.UUID] = set()
        parent_child_kb_ids: set[uuid.UUID] = set()

        for kb_id, cfg in kb_configs.items():
            kb_results = [r for r in results if r.chunk.kb_id == kb_id]
            if not kb_results:
                continue

            if cfg.chunking.general_strategy != ChunkingStrategy.PARENT_CHILD:
                for r in kb_results:
                    if not r.context_text:
                        r.context_text = r.chunk.content
                continue

            child_results = [
                r
                for r in kb_results
                if (r.chunk.chunk_role == "child" and r.chunk.parent_chunk_id)
            ]
            if not child_results:
                for r in kb_results:
                    if not r.context_text:
                        r.context_text = r.chunk.content
                continue

            parent_child_kb_ids.add(kb_id)
            parent_scores: dict[str, float] = {}
            for r in child_results:
                parent_id = r.chunk.parent_chunk_id
                if not parent_id:
                    continue
                parent_scores[parent_id] = max(
                    parent_scores.get(parent_id, -1e9), r.score
                )

            sorted_parents = sorted(
                parent_scores.items(), key=lambda item: item[1], reverse=True
            )[:max_parents]
            allowed_parents = {pid for pid, _ in sorted_parents}

            kept_children: dict[str, int] = {pid: 0 for pid in allowed_parents}
            for r in child_results:
                parent_id = r.chunk.parent_chunk_id
                if not parent_id or parent_id not in allowed_parents:
                    continue
                if kept_children[parent_id] >= max_children_per_parent:
                    continue
                kept_children[parent_id] += 1
                selected_child_ids.add(r.chunk.id)

            parent_ids.update(allowed_parents)

        if not selected_child_ids:
            for r in results:
                if not r.context_text:
                    r.context_text = r.chunk.content
            return results

        parent_map: dict[str, RetrievedChunk] = {}
        if parent_ids:
            parent_records = await self._run_with_timeout(
                self._milvus.query_by_chunk_ids(chunk_ids=list(parent_ids)),
                timeout_seconds,
            )
            for record in parent_records:
                chunk = self._build_chunk_from_record(record)
                if chunk:
                    parent_map[str(chunk.id)] = chunk
            await self._run_with_timeout(
                self._hydrate_chunks_from_postgres(list(parent_map.values())),
                timeout_seconds,
            )

        for r in results:
            if r.chunk.id in selected_child_ids:
                parent = parent_map.get(r.chunk.parent_chunk_id or "")
                r.context_text = parent.content if parent else r.chunk.content
            elif r.context_text is None:
                r.context_text = r.chunk.content

        ordered: list[RetrievalResult] = []
        for r in results:
            if r.chunk.kb_id in parent_child_kb_ids:
                if r.chunk.id in selected_child_ids:
                    ordered.append(r)
            else:
                ordered.append(r)
        return ordered

    @staticmethod
    def _window_key_from_metadata(metadata: dict | None) -> tuple[int, int] | None:
        if not isinstance(metadata, dict):
            return None
        size = metadata.get("window_size_tokens")
        overlap = metadata.get("window_overlap_tokens")
        if not isinstance(size, int) or not isinstance(overlap, int):
            return None
        return size, overlap

    async def _apply_query_dependent_multiscale_strategy(
        self,
        results: list[RetrievalResult],
        kb_configs: dict[uuid.UUID, IndexConfig],
        *,
        per_window_top_k: int,
        rrf_k: int,
        max_documents: int,
        max_chunks_per_document: int,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        if not results or not kb_configs:
            return results
        if timeout_seconds is not None and float(timeout_seconds) <= 0:
            raise asyncio.TimeoutError()

        multiscale_kb_ids = {
            kb_id
            for kb_id, cfg in kb_configs.items()
            if cfg.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
        }
        if not multiscale_kb_ids:
            return results

        selected_results: list[RetrievalResult] = []
        selected_chunk_ids: set[uuid.UUID] = set()

        for kb_id in multiscale_kb_ids:
            cfg = kb_configs.get(kb_id)
            if cfg is None:
                continue
            kb_results = [r for r in results if r.chunk.kb_id == kb_id]
            if not kb_results:
                continue

            by_window: dict[tuple[int, int], list[RetrievalResult]] = {}
            for item in kb_results:
                key = self._window_key_from_metadata(item.chunk.metadata)
                if key is None:
                    continue
                by_window.setdefault(key, []).append(item)

            if not by_window:
                continue

            ranked_doc_lists: list[list[tuple[str, str, str]]] = []
            for window_items in by_window.values():
                ranked = sorted(window_items, key=lambda row: row.score, reverse=True)
                ranked = ranked[:per_window_top_k]

                seen_materials: set[str] = set()
                doc_list: list[tuple[str, str, str]] = []
                for row in ranked:
                    material_id = str(row.chunk.material_id)
                    if material_id in seen_materials:
                        continue
                    seen_materials.add(material_id)
                    doc_list.append((str(row.chunk.kb_id), material_id, "__doc__"))
                if doc_list:
                    ranked_doc_lists.append(doc_list)

            if not ranked_doc_lists:
                continue

            doc_rrf_keys, _ = self._rrf_rank(
                ranked_doc_lists,
                k=rrf_k,
            )
            ordered_material_ids = [key[1] for key in doc_rrf_keys[:max_documents]]

            for material_id in ordered_material_ids:
                material_chunks = [
                    row
                    for row in kb_results
                    if str(row.chunk.material_id) == material_id
                ]
                material_chunks = sorted(
                    material_chunks,
                    key=lambda row: row.score,
                    reverse=True,
                )[:max_chunks_per_document]
                for row in material_chunks:
                    if row.chunk.id in selected_chunk_ids:
                        continue
                    selected_chunk_ids.add(row.chunk.id)
                    if row.context_text is None:
                        row.context_text = row.chunk.content
                    selected_results.append(row)

        if not selected_results:
            return results

        fallback_results: list[RetrievalResult] = []
        for row in results:
            if row.chunk.kb_id in multiscale_kb_ids:
                continue
            if row.context_text is None:
                row.context_text = row.chunk.content
            fallback_results.append(row)

        return selected_results + fallback_results

    async def retrieve(
        self,
        *,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int | None = None,
        timeout_seconds: float | None = None,
        feature_overrides: dict[str, object] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve from Milvus by chunk IDs."""
        deadline = self._make_deadline(timeout_seconds)
        feature_flags = self._resolve_feature_flags(feature_overrides)
        runtime_overrides = self._resolve_runtime_overrides(feature_overrides)
        if not kb_ids:
            self._last_layer_draft = self._empty_layer_draft()
            return []

        if deadline is not None and float(timeout_seconds) <= 0:
            normalized_query = self._normalize_query(query)
            if top_k is None:
                top_k = runtime_overrides.retrieval_top_k
            top_k = min(top_k, self._settings.retrieval_max_top_k)
            self._last_layer_draft = self._empty_layer_draft(reason="timeout")
            self._last_stats = RetrievalStats(
                query=query,
                normalized_query=normalized_query,
                effective_query=normalized_query,
                top_k=top_k,
                min_score=self._settings.retrieval_min_score,
                total_hits=0,
                filtered_count=0,
                returned_count=0,
                cache_hit=False,
                rewrite_enabled=feature_flags.query_rewrite_enabled,
                rewrite_applied=False,
                rewrite_reason="timeout",
                rewrite_latency_ms=None,
                hybrid_enabled=feature_flags.hybrid_enabled,
                rerank_enabled=feature_flags.rerank_enabled,
                reason="timeout",
            )
            return []

        normalized_query = self._normalize_query(query)

        # Run in batches to avoid oversized queries.
        if top_k is None:
            top_k = runtime_overrides.retrieval_top_k
        top_k = min(top_k, self._settings.retrieval_max_top_k)

        def _timeout_return() -> list[RetrievalResult]:
            self._last_layer_draft = self._empty_layer_draft(reason="timeout")
            self._last_stats = RetrievalStats(
                query=query,
                normalized_query=normalized_query,
                effective_query=normalized_query,
                top_k=top_k,
                min_score=self._settings.retrieval_min_score,
                total_hits=0,
                filtered_count=0,
                returned_count=0,
                cache_hit=False,
                rewrite_enabled=feature_flags.query_rewrite_enabled,
                rewrite_applied=False,
                rewrite_reason="timeout",
                rewrite_latency_ms=None,
                hybrid_enabled=feature_flags.hybrid_enabled,
                rerank_enabled=feature_flags.rerank_enabled,
                reason="timeout",
            )
            return []

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            kb_configs = await self._run_with_timeout(
                self._load_kb_index_configs(kb_ids), timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_return()
        kb_fingerprint = self._build_kb_fingerprint(kb_configs)

        remaining = self._remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            return _timeout_return()
        rewrite_result = await self._maybe_rewrite_query(
            normalized_query,
            enabled=feature_flags.query_rewrite_enabled,
        )
        effective_query = rewrite_result.query or normalized_query
        if not effective_query.strip():
            effective_query = normalized_query
            rewrite_result = RewriteResult(
                query=effective_query,
                rewritten=False,
                reason="empty",
                latency_ms=rewrite_result.latency_ms,
            )

        strategy = self._strategy_fingerprint(
            top_k,
            feature_flags=feature_flags,
            runtime_overrides=runtime_overrides,
            kb_fingerprint=kb_fingerprint,
        )
        cache_key = self._cache_key(effective_query, kb_ids, top_k, strategy)
        if self._redis and self._settings.retrieval_cache_enabled:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            if timeout_value is not None and timeout_value <= 0:
                return _timeout_return()
            try:
                cached = await self._run_with_timeout(
                    self._redis.get(cache_key), timeout_value
                )
            except asyncio.TimeoutError:
                return _timeout_return()
            except Exception as exc:  # pragma: no cover
                logger.warning("Retrieval cache read failed; continue without cache.", extra={"error": str(exc)})
                cached = None
            if cached:
                timeout_value = self._effective_timeout(
                    deadline=deadline, per_call_timeout=None
                )
                if timeout_value is not None and timeout_value <= 0:
                    return _timeout_return()
                try:
                    results = await self._run_with_timeout(
                        self._load_from_cache(cached), timeout_value
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if timeout_value is not None and timeout_value <= 0:
                        return _timeout_return()
                    await self._run_with_timeout(
                        self._hydrate_chunks_from_postgres(
                            [r.chunk for r in results]
                        ),
                        timeout_value,
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if timeout_value is not None and timeout_value <= 0:
                        return _timeout_return()
                    results = await self._apply_parent_child_strategy(
                        results, kb_configs, timeout_seconds=timeout_value
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if timeout_value is not None and timeout_value <= 0:
                        return _timeout_return()
                    await self._run_with_timeout(
                        self._ensure_chunk_citation_labels(
                            [r.chunk for r in results]
                        ),
                        timeout_value,
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()

                # Cache path has no per-query provenance. Still expose evidence draft.
                evidence_items: list[dict] = []
                for r in results:
                    evidence_items.append(
                        {
                            "source_kind": "kb",
                            "kb_id": str(r.chunk.kb_id),
                            "material_id": str(r.chunk.material_id),
                            "chunk_id": str(r.chunk.id),
                            "locator": r.chunk.locator,
                            "excerpt": self._result_excerpt(r),
                            "score": float(r.score),
                            "hits": [],
                        }
                    )
                self._last_layer_draft = RetrievalLayerDraft(
                    retrieval_candidates=[],
                    reranked_candidates=[],
                    evidence_items=evidence_items,
                    results=results,
                    stats={
                        "cache_hit": True,
                        "filtered_count": 0,
                    },
                )

                self._last_stats = RetrievalStats(
                    query=query,
                    normalized_query=normalized_query,
                    effective_query=effective_query,
                    top_k=top_k,
                    min_score=self._settings.retrieval_min_score,
                    total_hits=len(results),
                    filtered_count=0,
                    returned_count=len(results),
                    cache_hit=True,
                    rewrite_enabled=feature_flags.query_rewrite_enabled,
                    rewrite_applied=rewrite_result.rewritten,
                    rewrite_reason=rewrite_result.reason,
                    rewrite_latency_ms=rewrite_result.latency_ms,
                    hybrid_enabled=feature_flags.hybrid_enabled,
                    rerank_enabled=feature_flags.rerank_enabled,
                )
                return results

        # Unified retrieval layer: hybrid_search + global RRF (+ optional rerank) + Top-N.
        query_items = build_query_items(main_query=effective_query)
        remaining = self._remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            return _timeout_return()
        layer = await self.retrieve_layer(
            query_items=query_items,
            kb_ids=kb_ids,
            top_n=top_k,
            per_query_top_k=top_k,
            # Keep defaults conservative: global cap and rerank cap follow Settings max_top_k.
            global_candidates_limit=self._settings.retrieval_max_top_k,
            rerank_input_limit=runtime_overrides.retrieval_rerank_top_k,
            timeout_seconds=remaining,
            feature_overrides={
                "query_rewrite_enabled": feature_flags.query_rewrite_enabled,
                "hybrid_retrieval_enabled": feature_flags.hybrid_enabled,
                "rerank_enabled": feature_flags.rerank_enabled,
                "hybrid_rrf_k": runtime_overrides.hybrid_rrf_k,
                "retrieval_top_k": runtime_overrides.retrieval_top_k,
                "retrieval_rerank_top_k": runtime_overrides.retrieval_rerank_top_k,
                "parent_max_parents": runtime_overrides.parent_max_parents,
                "parent_max_children_per_parent": runtime_overrides.parent_max_children_per_parent,
                "multiscale_per_window_top_k": runtime_overrides.multiscale_per_window_top_k,
                "multiscale_rrf_k": runtime_overrides.multiscale_rrf_k,
                "multiscale_max_documents": runtime_overrides.multiscale_max_documents,
                "multiscale_max_chunks_per_document": runtime_overrides.multiscale_max_chunks_per_document,
            },
        )
        results = layer.results
        total_hits = int(
            layer.stats.get("pre_min_score_candidates")
            or layer.stats.get("rrf_candidates")
            or 0
        )
        filtered_count = int(layer.stats.get("filtered_count") or 0)

        if not results:
            self._last_stats = RetrievalStats(
                query=query,
                normalized_query=normalized_query,
                effective_query=effective_query,
                top_k=top_k,
                min_score=self._settings.retrieval_min_score,
                total_hits=0,
                filtered_count=0,
                returned_count=0,
                cache_hit=False,
                rewrite_enabled=feature_flags.query_rewrite_enabled,
                rewrite_applied=rewrite_result.rewritten,
                rewrite_reason=rewrite_result.reason,
                rewrite_latency_ms=rewrite_result.latency_ms,
                hybrid_enabled=feature_flags.hybrid_enabled,
                rerank_enabled=feature_flags.rerank_enabled,
                reason=cast(str | None, layer.stats.get("reason")),
            )
            return []

        # Cache retrieval results.
        if self._redis and self._settings.retrieval_cache_enabled and results:
            cache_data = [
                {"chunk_id": str(r.chunk.id), "score": r.score} for r in results
            ]
            try:
                await self._redis.set(
                    cache_key,
                    json.dumps(cache_data),
                    ex=self._settings.retrieval_cache_ttl_seconds,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Retrieval cache write failed; skip cache.", extra={"error": str(exc)})

        self._last_stats = RetrievalStats(
            query=query,
            normalized_query=normalized_query,
            effective_query=effective_query,
            top_k=top_k,
            min_score=self._settings.retrieval_min_score,
            total_hits=total_hits,
            filtered_count=filtered_count,
            returned_count=len(results),
            cache_hit=False,
            rewrite_enabled=feature_flags.query_rewrite_enabled,
            rewrite_applied=rewrite_result.rewritten,
            rewrite_reason=rewrite_result.reason,
            rewrite_latency_ms=rewrite_result.latency_ms,
            hybrid_enabled=feature_flags.hybrid_enabled,
            rerank_enabled=feature_flags.rerank_enabled,
            rerank_applied=bool(layer.stats.get("rerank_applied")),
            rerank_reason=cast(str | None, layer.stats.get("rerank_reason")),
            rerank_latency_ms=cast(int | None, layer.stats.get("rerank_latency_ms")),
            reason=cast(str | None, layer.stats.get("reason")),
        )

        return results

    async def _load_from_cache(self, cached: str) -> list[RetrievalResult]:
        """Load retrieval results from cache payload."""
        data = json.loads(cached)
        chunk_ids = [str(item["chunk_id"]) for item in data]
        scores = {str(item["chunk_id"]): item["score"] for item in data}

        records = await self._milvus.query_by_chunk_ids(chunk_ids=chunk_ids)
        chunks_map: dict[str, RetrievedChunk] = {}
        for record in records:
            chunk = self._build_chunk_from_record(record)
            if chunk:
                chunks_map[str(chunk.id)] = chunk

        results: list[RetrievalResult] = []
        for item in data:
            chunk = chunks_map.get(str(item["chunk_id"]))
            if chunk:
                results.append(
                    RetrievalResult(
                        chunk=chunk,
                        score=scores[str(item["chunk_id"])],
                    )
                )
        return results

    def _resolve_stage_score_cutoff(
        self,
        *,
        stage: Literal["raw", "rank_fusion", "rerank"],
    ) -> float | None:
        if stage == "raw":
            cutoff = self._settings.retrieval_raw_min_score
            return cutoff if cutoff is not None else None

        if stage == "rank_fusion":
            cutoff = self._settings.retrieval_rank_fusion_min_score
            if cutoff is not None:
                return cutoff
            # Rank-based fusion scores are not calibrated against raw/rerank scores.
            # Keep legacy RETRIEVAL_MIN_SCORE from clearing RRF candidates.
            return None

        cutoff = self._settings.retrieval_rerank_min_score
        if cutoff is not None:
            return cutoff
        return self._settings.retrieval_min_score

    def _apply_stage_score_cutoff(
        self,
        results: list[RetrievalResult],
        *,
        stage: Literal["raw", "rank_fusion", "rerank"],
    ) -> tuple[list[RetrievalResult], int]:
        min_score = self._resolve_stage_score_cutoff(stage=stage)
        if min_score is None or min_score <= 0:
            return results, 0
        filtered = [r for r in results if r.score >= min_score]
        return filtered, max(len(results) - len(filtered), 0)

    def _apply_min_score(
        self, results: list[RetrievalResult]
    ) -> tuple[list[RetrievalResult], int]:
        return self._apply_stage_score_cutoff(results, stage="raw")

    def to_evidence_items(self, results: list[RetrievalResult]) -> list[EvidenceItem]:
        """Convert retrieval results to evidence items."""
        items: list[EvidenceItem] = []
        for r in results:
            items.append(
                EvidenceItem(
                    source_kind=EvidenceSourceKind.KB,
                    kb_id=r.chunk.kb_id,
                    material_id=r.chunk.material_id,
                    chunk_id=r.chunk.id,
                    locator=r.chunk.locator,
                    excerpt=r.chunk.content[:500],
                )
            )
        return items
