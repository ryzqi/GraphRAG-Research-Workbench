"""KB Chat LangGraph 构建器（仅保留 agentic 路径）。

已移除旧版基于 ToolCallingGraph 的实现。
KB Chat 现在固定走结构化 agentic RAG 流程。
"""

from __future__ import annotations

from typing import Any

from langchain.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.agents.kb_chat_agentic.model_guard import guard_kb_chat_model
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings


def build_kb_chat_graph(
    *,
    chat_model: BaseChatModel,
    tools: list[BaseTool],
    tool_meta_by_name: dict[str, ToolMeta],
    kb_chat_config: dict[str, Any] | None = None,
) -> KbChatAgenticGraph:
    settings = get_settings()
    return KbChatAgenticGraph(
        chat_model=guard_kb_chat_model(chat_model, settings=settings),
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        kb_chat_config=kb_chat_config,
    )
