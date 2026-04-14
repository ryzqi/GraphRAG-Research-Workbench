from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Literal, cast

from app.schemas.chats import EvidenceItem, EvidenceSourceKind
from app.services.query_rewrite_service import RewriteResult, build_query_items
from app.services.retrieval_service_contracts import (
    RetrievalLayerDraft,
    RetrievalResult,
    RetrievalServiceProtocol,
    RetrievalStats,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)


class RetrievalRetrieveMixin(RetrievalServiceProtocol):
    async def retrieve(
        self,
        *,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int | None = None,
        timeout_seconds: float | None = None,
        feature_overrides: dict[str, object] | None = None,
    ) -> list[RetrievalResult]:
        """按 chunk ID 从 Milvus 检索。"""
        deadline = self._make_deadline(timeout_seconds)
        feature_flags = self._resolve_feature_flags(feature_overrides)
        runtime_overrides = self._resolve_runtime_overrides(feature_overrides)
        if not kb_ids:
            self._last_layer_draft = self._empty_layer_draft()
            return []

        if timeout_seconds is not None and timeout_seconds <= 0:
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

        # 分批执行，避免查询体积过大。
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
        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            kb_content_version = await self._run_with_timeout(
                self._build_kb_content_version(kb_ids), timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_return()
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Retrieval content version build failed; fallback to unknown version.",
                extra={"error": str(exc)},
            )
            kb_content_version = "kb_unknown"

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
        cache_key = self._cache_key(
            effective_query,
            kb_ids,
            top_k,
            strategy,
            kb_content_version,
        )
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
                logger.warning(
                    "Retrieval cache read failed; continue without cache.",
                    extra={"error": str(exc)},
                )
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
                        self._hydrate_chunks_from_postgres([r.chunk for r in results]),
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
                        results,
                        kb_configs,
                        max_parents=runtime_overrides.parent_max_parents,
                        max_children_per_parent=runtime_overrides.parent_max_children_per_parent,
                        timeout_seconds=timeout_value,
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
                        self._ensure_chunk_citation_labels([r.chunk for r in results]),
                        timeout_value,
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()

                # 缓存路径没有逐查询来源信息，但仍需暴露证据草稿。
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

        # 统一检索层：hybrid_search + 全局 RRF（可选 rerank）+ Top-N。
        query_items = build_query_items(main_query=effective_query)
        remaining = self._remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            return _timeout_return()
        layer = await self.retrieve_layer(
            query_items=query_items,
            kb_ids=kb_ids,
            top_n=top_k,
            per_query_top_k=top_k,
            # 默认值保持保守：全局上限与 rerank 上限均跟随 Settings.max_top_k。
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
        total_hits = self._int_from_object(
            layer.stats.get("pre_min_score_candidates")
            or layer.stats.get("rrf_candidates")
        )
        filtered_count = self._int_from_object(layer.stats.get("filtered_count"))

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

        # 缓存检索结果。
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
                logger.warning(
                    "Retrieval cache write failed; skip cache.",
                    extra={"error": str(exc)},
                )

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
        """从缓存载荷中加载检索结果。"""
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
            # 基于排名的融合分数未与原始分数或 rerank 分数校准。
            # 避免旧版 RETRIEVAL_MIN_SCORE 误清理 RRF 候选项。
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
        """将检索结果转换为证据项。"""
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
