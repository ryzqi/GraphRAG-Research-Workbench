"""知识库检索工具（kb_retrieve）。

用于 ToolNode/工具调用框架：
- 返回带标签的引用片段（便于回答中使用 [agent基础] 这类引用）
- 通过回调将结构化检索结果交给上层（用于 Evidence 落库/指标）
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from langchain.tools import BaseTool
from langchain.tools import tool as lc_tool
from pydantic import BaseModel, Field

from app.agents.tool_calling.utils import (
    DEFAULT_TOOL_OUTPUT_MAX_CHARS,
    truncate_tool_output,
)
from app.core.settings import get_settings
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalResult, RetrievalService

logger = logging.getLogger(__name__)


class KbRetrieveArgs(BaseModel):
    """kb_retrieve 工具参数。"""

    query: str = Field(..., description="检索问题")
    kb_ids: list[str] | None = Field(default=None, description="知识库 ID 列表")
    top_k: int | None = Field(default=None, ge=1, le=50, description="返回条数")
    timeout_seconds: float | None = Field(
        default=None, description="可选：检索/重排超时（秒）。"
    )
    query_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="可选：统一检索层 QueryItem 列表（用于多路/分解/HyDE fanout 融合）。提供时将优先使用该列表进行融合检索。",
    )
    retrieval_round: int | None = Field(
        default=None,
        ge=0,
        description="可选：检索轮次（用于将证据与最终答案绑定到同一轮检索上下文）。",
    )


def _citation_id(index: int) -> str:
    return f"S{index}"


def _citation_title_from_result(result: RetrievalResult, *, index: int) -> str:
    chunk = getattr(result, "chunk", None)
    locator = getattr(chunk, "locator", None)
    if isinstance(locator, dict):
        raw = locator.get("citation_label")
        if isinstance(raw, str) and raw.strip():
            normalized = " ".join(raw.replace("[", " ").replace("]", " ").split())
            if normalized:
                return normalized
        filename = locator.get("filename")
        if isinstance(filename, str) and filename.strip():
            base = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
            stem = base.rsplit(".", 1)[0] if "." in base else base
            normalized = " ".join(stem.replace("[", " ").replace("]", " ").split())
            if normalized:
                return normalized
    return f"资料{index}"


def _citation_source_from_result(result: RetrievalResult) -> str | None:
    chunk = getattr(result, "chunk", None)
    locator = getattr(chunk, "locator", None)
    if not isinstance(locator, dict):
        return None
    filename = locator.get("filename")
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    source = locator.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    return None


def build_kb_retrieve_tool(
    *,
    retrieval: RetrievalService,
    default_kb_ids: list[uuid.UUID],
    retrieval_overrides: dict[str, bool] | None = None,
    context_builder: ContextBuilder | None = None,
    tool_output_max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS,
    on_results: Callable[[list[RetrievalResult], dict[str, Any]], None] | None = None,
) -> BaseTool:
    """构建 kb_retrieve 工具。"""

    async def _retrieve(
        query: str,
        kb_ids: list[str] | None = None,
        top_k: int | None = None,
        timeout_seconds: float | None = None,
        query_items: list[dict[str, Any]] | None = None,
        retrieval_round: int | None = None,
    ) -> str:
        allowed_kb_ids = list(default_kb_ids)
        requested_raw = kb_ids or []
        requested_ids: list[uuid.UUID] = []
        invalid_count = 0
        for raw in requested_raw:
            try:
                requested_ids.append(uuid.UUID(str(raw)))
            except ValueError:
                invalid_count += 1
                continue

        fallback_to_allowed = False
        if not requested_ids:
            resolved = allowed_kb_ids
        else:
            allowed_set = set(allowed_kb_ids)
            resolved = [kid for kid in requested_ids if kid in allowed_set]
            if not resolved:
                fallback_to_allowed = True
                resolved = allowed_kb_ids
                logger.warning(
                    "kb_retrieve requested kb_ids outside allowed scope; fallback to allowed",
                    extra={
                        "requested_count": len(requested_ids),
                        "allowed_count": len(allowed_kb_ids),
                    },
                )

        kb_scope = {
            "allowed_count": len(allowed_kb_ids),
            "requested_count": len(requested_ids),
            "applied_count": len(resolved),
            "denied_count": max(len(requested_ids) - len(resolved), 0),
            "invalid_count": invalid_count,
            "fallback_to_allowed": fallback_to_allowed,
        }

        if isinstance(query_items, list) and query_items:
            # Agentic KB chat passes a fanout query bundle (sub-queries/variants/HyDE).
            # Use the unified RetrievalLayer so cross-query fusion (RRF/rerank/Top-N) actually takes effect.
            settings = get_settings()
            top_n = (
                int(top_k)
                if top_k is not None
                else int(settings.retrieval_default_top_k)
            )
            layer = await retrieval.retrieve_layer(
                query_items=query_items,
                kb_ids=resolved,
                top_n=top_n,
                per_query_top_k=top_n,
                timeout_seconds=timeout_seconds,
                feature_overrides=retrieval_overrides,
            )
            results = layer.results
        else:
            results = await retrieval.retrieve(
                query=query,
                kb_ids=resolved,
                top_k=top_k,
                timeout_seconds=timeout_seconds,
                feature_overrides=retrieval_overrides,
            )

        if context_builder is None:
            included = results
            parts = [
                f"[{_citation_id(i)}] {r.context_text or r.chunk.content}"
                for i, r in enumerate(included, 1)
            ]
            context = "\n\n".join(parts) if parts else "（未找到相关内容）"
            usage = {"tokens": 0, "chars": len(context), "items": len(included)}
            truncation: dict[str, int | bool] = {
                "truncated": False,
                "dropped_items": 0,
                "dropped_tokens": 0,
            }
        else:
            context, included, usage, truncation = (
                context_builder.build_retrieval_context(results)
            )

        if truncation.get("truncated"):
            context = f"{context}\n\n（输出已截断）"

        context, char_truncated = truncate_tool_output(context, tool_output_max_chars)

        if on_results is not None:
            # Build a unified, JSON-friendly evidence draft (chunk-level) for auditing/persistence.
            draft_by_chunk_id: dict[str, dict[str, Any]] = {}
            layer = getattr(retrieval, "last_layer_draft", None)
            layer_items = (
                getattr(layer, "evidence_items", None) if layer is not None else None
            )
            if isinstance(layer_items, list):
                for it in layer_items:
                    if isinstance(it, dict):
                        cid = it.get("chunk_id")
                        if isinstance(cid, str) and cid:
                            draft_by_chunk_id[cid] = it

            evidence_items: list[dict[str, Any]] = []
            for i, r in enumerate(included, 1):
                citation_id = _citation_id(i)
                citation_title = _citation_title_from_result(r, index=i)
                citation_source = _citation_source_from_result(r)
                chunk_id = getattr(getattr(r, "chunk", None), "id", None)
                if chunk_id is None:
                    continue
                cid = str(chunk_id)
                # Evidence excerpts should match what the model saw in the retrieval context
                # (context_text may be parent content under parent/child strategy).
                excerpt_text = str(r.context_text or r.chunk.content or "")[:500]
                item = draft_by_chunk_id.get(cid)
                if item is None:
                    chunk = getattr(r, "chunk", None)
                    kb_id = getattr(chunk, "kb_id", None)
                    material_id = getattr(chunk, "material_id", None)
                    evidence_items.append(
                        {
                            "source_kind": "kb",
                            "kb_id": str(kb_id) if kb_id else "",
                            "material_id": str(material_id) if material_id else "",
                            "chunk_id": cid,
                            "locator": getattr(chunk, "locator", None),
                            "excerpt": excerpt_text,
                            "score": float(getattr(r, "score", 0.0) or 0.0),
                            "hits": [],
                            "citation_id": citation_id,
                            "citation_title": citation_title,
                            "citation_source": citation_source,
                        }
                    )
                else:
                    merged = dict(item)
                    merged["excerpt"] = excerpt_text
                    merged["citation_id"] = citation_id
                    merged["citation_title"] = citation_title
                    merged["citation_source"] = citation_source
                    evidence_items.append(merged)

            on_results(
                included,
                {
                    "count": len(included),
                    "usage": usage,
                    "truncation": truncation,
                    "char_truncated": char_truncated,
                    "evidence_items": evidence_items,
                    "citation_catalog": [
                        {
                            "citation_id": it.get("citation_id"),
                            "title": it.get("citation_title"),
                            "source": it.get("citation_source"),
                            "locator": it.get("locator"),
                            "chunk_id": it.get("chunk_id"),
                            "material_id": it.get("material_id"),
                            "kb_id": it.get("kb_id"),
                        }
                        for it in evidence_items
                    ],
                    "kb_scope": kb_scope,
                    "retrieval_round": retrieval_round
                    if isinstance(retrieval_round, int)
                    else None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        return context

    return lc_tool(
        "kb_retrieve",
        description="从知识库检索资料，返回带编号的引用片段。",
        args_schema=KbRetrieveArgs,
    )(_retrieve)
