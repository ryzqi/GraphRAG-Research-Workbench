from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import select

from app.integrations.rerank_client import RerankClient
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.services.retrieval_service_contracts import (
    RetrievalResult,
    RetrievedChunk,
    RetrievalServiceProtocol,
)

logger = logging.getLogger(__name__)


class RetrievalStrategyMixin(RetrievalServiceProtocol):
    async def _build_kb_content_version(self, kb_ids: list[uuid.UUID]) -> str:
        if not kb_ids or self._db is None:
            return "kb_none"

        stmt = (
            select(KnowledgeBase.id, KnowledgeBase.updated_at)
            .where(KnowledgeBase.id.in_(kb_ids))
            .order_by(KnowledgeBase.id.asc())
        )
        rows = await self._db_execute(stmt)
        updated_at_by_id = {str(kb_id): updated_at for kb_id, updated_at in rows.all()}
        payload: list[dict[str, str]] = []
        for kb_id in sorted(kb_ids, key=str):
            updated_at = updated_at_by_id.get(str(kb_id))
            updated_at_text = ""
            if isinstance(updated_at, datetime):
                updated_at_text = updated_at.isoformat()
            elif updated_at is not None:
                updated_at_text = str(updated_at)
            payload.append(
                {
                    "id": str(kb_id),
                    "updated_at": updated_at_text,
                }
            )
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

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
        """按需对候选项 rerank，并在失败时平滑降级。"""
        rerank_enabled = True if enabled is None else bool(enabled)
        if not rerank_enabled:
            return results, False, "disabled", None

        if not results:
            return results, False, "empty_candidates", None

        reranker = self._reranker or RerankClient(self._settings)
        self._reranker = reranker

        # Rerank 是可选的质量增强：需保持在配置的软预算内，并
        # 在 reranker 过慢时平滑降级到原始排序。
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
            logger.warning(
                "Rerank timed out; fallback to original order.",
                extra={"timeout": timeout_value},
            )
            return results, False, "timeout", None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Rerank failed; fallback to original order.", extra={"error": str(exc)}
            )
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

        # 对未被 rerank 返回的项保留原始顺序。
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
        snapshot_stmt = select(
            KBConfigSnapshot.kb_id, KBConfigSnapshot.config_json
        ).where(
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
    def _build_kb_fingerprint(
        configs: dict[uuid.UUID, IndexConfig],
    ) -> dict[str, dict[str, object]]:
        if not configs:
            return {}
        fingerprint: dict[str, dict[str, object]] = {}
        for kb_id, cfg in configs.items():
            item: dict[str, object] = {
                "general_strategy": cfg.chunking.general_strategy.value,
            }
            if (
                cfg.chunking.general_strategy
                == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
            ):
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
            if cfg.chunking.general_strategy
            == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
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
