"""知识库检索工具（kb_retrieve）。

用于 ToolNode/工具调用框架：
- 返回带编号的引用片段（便于回答中使用 [1]、[2] 引用）
- 通过回调将结构化检索结果交给上层（用于 Evidence 落库/指标）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, Field

from app.agents.tool_calling.utils import DEFAULT_TOOL_OUTPUT_MAX_CHARS, truncate_tool_output
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalResult, RetrievalService


class KbRetrieveArgs(BaseModel):
    """kb_retrieve 工具参数。"""

    query: str = Field(..., description="检索问题")
    kb_ids: list[str] | None = Field(default=None, description="知识库 ID 列表")
    top_k: int | None = Field(default=None, ge=1, le=50, description="返回条数")



def build_kb_retrieve_tool(
    *,
    retrieval: RetrievalService,
    default_kb_ids: list[uuid.UUID],
    context_builder: ContextBuilder | None = None,
    tool_output_max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS,
    on_results: Callable[[list[RetrievalResult], dict[str, Any]], None] | None = None,
) -> BaseTool:
    """构建 kb_retrieve 工具。"""

    async def _retrieve(
        query: str,
        kb_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> str:
        resolved: list[uuid.UUID] = []
        for raw in kb_ids or []:
            try:
                resolved.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        if not resolved:
            resolved = default_kb_ids

        results = await retrieval.retrieve(query=query, kb_ids=resolved, top_k=top_k)

        if context_builder is None:
            included = results
            parts = [f"[{i}] {r.chunk.text}" for i, r in enumerate(included, 1)]
            context = "\n\n".join(parts) if parts else "（未找到相关内容）"
            usage = {"tokens": 0, "chars": len(context), "items": len(included)}
            truncation: dict[str, int | bool] = {
                "truncated": False,
                "dropped_items": 0,
                "dropped_tokens": 0,
            }
        else:
            context, included, usage, truncation = context_builder.build_retrieval_context(results)

        if truncation.get("truncated"):
            context = f"{context}\n\n（输出已截断）"

        context, char_truncated = truncate_tool_output(context, tool_output_max_chars)

        if on_results is not None:
            on_results(
                included,
                {
                    "count": len(included),
                    "usage": usage,
                    "truncation": truncation,
                    "char_truncated": char_truncated,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        return context

    return lc_tool(
        "kb_retrieve",
        description="从知识库检索资料，返回带编号的引用片段。",
        args_schema=KbRetrieveArgs,
    )(_retrieve)
