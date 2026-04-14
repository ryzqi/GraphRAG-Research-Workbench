from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import uuid
from typing import cast

from app.integrations.embedding_client import EmbeddingCallError
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.schemas.query_enhancement import QueryHitSource, QueryItem
from app.services.query_dependent_collections import collection_name_for_window
from app.services.query_rewrite_service import (
    QueryRewriteService,
    RewriteResult,
)
from app.services.query_rewrite_text import _hyde_aggregation, _hyde_num_hypotheses
from app.services.retrieval_service_contracts import (
    DEFAULT_RESULT_EXCERPT_MAX_CHARS,
    EXPANDED_RESULT_EXCERPT_MAX_CHARS,
    RetrievalFeatureFlags,
    RetrievalResult,
    RetrievalRuntimeOverrides,
    RetrievedChunk,
    RetrievalServiceProtocol,
)

logger = logging.getLogger(__name__)


class RetrievalRuntimeMixin(RetrievalServiceProtocol):
    def _cache_key(
        self,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int,
        strategy: dict,
        kb_content_version: str,
    ) -> str:
        """构建检索缓存键。"""
        kb_str = ",".join(sorted(str(k) for k in kb_ids))
        fingerprint = json.dumps(strategy, sort_keys=True, ensure_ascii=False)
        raw = (
            f"retrieval:{query}:{kb_str}:{top_k}:{kb_content_version}:{fingerprint}"
        )
        return f"retrieval:{hashlib.md5(raw.encode()).hexdigest()}"

    def _embedding_cache_key(self, query: str) -> str:
        """构建 embedding 缓存键。"""
        return f"embedding:{hashlib.md5(query.encode()).hexdigest()}"

    def _rewrite_cache_key(self, query: str) -> str:
        """构建查询改写缓存键。"""
        return f"rewrite:{hashlib.md5(query.encode()).hexdigest()}"

    def _strategy_fingerprint(
        self,
        top_k: int,
        *,
        feature_flags: RetrievalFeatureFlags,
        runtime_overrides: RetrievalRuntimeOverrides,
        kb_fingerprint: dict[str, dict[str, object]] | None = None,
    ) -> dict:
        """构建稳定的策略指纹，用于生成检索缓存键。"""
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
        text = RetrievalRuntimeMixin._result_text(result)
        if not text:
            return ""
        # 在控制成本的同时保留足够语义，用于相似度打分。
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
        """在检索前规范化输入查询。"""
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
        """获取带缓存支持的查询 embedding。"""
        if self._redis and self._settings.retrieval_cache_enabled:
            cache_key = self._embedding_cache_key(query)
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding cache read failed; skip cache.",
                    extra={"error": str(exc)},
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

        # Embedding 可在改写与检索变体之间复用，因此缓存时间可略长于
        # 短生命周期的检索结果缓存。
        if self._redis and self._settings.retrieval_cache_enabled:
            try:
                await self._redis.set(
                    self._embedding_cache_key(query),
                    json.dumps(embeddings[0]),
                    ex=self._settings.retrieval_cache_ttl_seconds * 2,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding cache write failed; skip cache.",
                    extra={"error": str(exc)},
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
        """解析查询 embedding；存在 HyDE 批量结果时同时聚合。"""
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
                if len(hyde_queries) >= _hyde_num_hypotheses():
                    break
        if not hyde_queries:
            hyde_queries = [query]

        aggregation = (
            str(item.get("hyde_aggregation") or "").strip().lower()
            or _hyde_aggregation()
        )
        if aggregation != _hyde_aggregation():
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
            # 平滑降级到第一条可用样本。
            return vectors[0], len(hyde_queries), 1, "dim_mismatch_first_sample"
        return merged, len(hyde_queries), len(vectors), "none"

    async def _maybe_rewrite_query(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> RewriteResult:
        """按需改写查询。"""
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
                    "Rewrite cache read failed; continue rewrite flow.",
                    extra={"error": str(exc)},
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
        # 为跨知识库 / 材料的全局去重保持稳定且显式的键。
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
        """Reciprocal Rank Fusion（RRF）。

        返回 `(ordered_keys, score_by_key)`。
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
            if (
                cfg.chunking.general_strategy
                != ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
            ):
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
            if (
                cfg.chunking.general_strategy
                == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
            ):
                multiscale_kb_ids.append(str(kb_id))
            else:
                default_kb_ids.append(str(kb_id))
        return default_kb_ids, multiscale_kb_ids
