from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence

from app.schemas.query_enhancement import QueryHitSource, QueryItem
from app.services.query_rewrite_text import _hyde_aggregation
from app.services.retrieval_service_contracts import (
    DEDUP_EMBEDDING_SIMILARITY_THRESHOLD,
    QUERY_FANOUT_CONCURRENCY,
    RetrievalLayerDraft,
    RetrievalResult,
    RetrievedChunk,
    RetrievalServiceProtocol,
)

logger = logging.getLogger(__name__)


class RetrievalLayerOpsMixin(RetrievalServiceProtocol):
    async def retrieve_layer(
        self,
        *,
        query_items: Sequence[QueryItem],
        kb_ids: list[uuid.UUID],
        top_n: int,
        per_query_top_k: int | None = None,
        global_candidates_limit: int | None = None,
        rerank_input_limit: int | None = None,
        extra_filter_expr: str | None = None,
        timeout_seconds: float | None = None,
        feature_overrides: dict[str, object] | None = None,
    ) -> RetrievalLayerDraft:
        """统一 RetrievalLayer：native hybrid_search + 全局 RRF + 可选 rerank + Top-N。

        NOTE: Any retry/transform query loop should come back to THIS method to ensure
        the retrieval chain stays consistent (hybrid_search+RRF+optional rerank).
        """

        deadline = self._make_deadline(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds <= 0:
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

        # 强制施加合理上限，作为生产护栏。
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
            # 最坏情况下每个查询产生一组混合结果，并为扇出额外预留余量。
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

        # 优先使用“main”查询作为 rerank 查询，若不存在则退回首个可用查询。
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
                retrieval_hits: Sequence[object],
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

            async def _run_sparse_fallback(
                reason: str,
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
            hybrid_hits.extend(await _safe_hybrid(kb_id_values=default_kb_id_strs))
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
            if isinstance(result, BaseException):
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
                        _hyde_aggregation() if hyde_requested_total > 0 else None
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

        # 按全局 RRF 顺序构建 RetrievalResult 列表。
        rrf_results: list[RetrievalResult] = []
        for key in global_keys:
            chunk = chunk_by_key.get(key)
            if chunk is None:
                continue
            rrf_results.append(
                RetrievalResult(chunk=chunk, score=global_scores.get(key, 0.0))
            )

        # 优先使用 Milvus 的 output_fields；仅在必要时再回填 Postgres 数据。
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

        # 为支持 multiscale 路由，kb_configs 已在检索循环前加载完成。
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
                logger.warning(
                    "Semantic-similarity dedupe timed out; skip this dedupe step."
                )
                dedup_similarity_reason = "dedupe:timeout"
                optional_embedding_skips.append(dedup_similarity_reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Semantic-similarity dedupe failed; keep original candidates.",
                    extra={"error": str(exc)},
                )
                dedup_similarity_reason = self._embedding_failure_reason(
                    exc,
                    fallback_stage="dedupe",
                )
                optional_embedding_skips.append(dedup_similarity_reason)
        post_dedup_count = len(rrf_results)

        candidates_for_rerank = rrf_results[:rerank_input_limit]

        # Rerank 流程：RRF → rerank → Top-N，输入还会额外受限。
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
                # Rerank 是可选步骤；超时时退回 RRF 顺序。
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
                candidate_results, rerank_filtered_count = (
                    self._apply_stage_score_cutoff(
                        candidate_results,
                        stage="rerank",
                    )
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
                logger.warning(
                    "Heading-path context enrichment timed out; keep original excerpts"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Heading-path context enrichment failed; keep original excerpts",
                    extra={"error": str(exc)},
                )

        # 为 agentic 状态和审计构建更适合 JSON 的草稿数据。
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
                "hyde_aggregation": _hyde_aggregation()
                if hyde_requested_total > 0
                else None,
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
