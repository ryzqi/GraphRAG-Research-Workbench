"""KB Chat LangGraph builder (agentic-only).

We intentionally removed the legacy ToolCallingGraph-based KB chat implementation.
KB chat now always runs the structured agentic RAG flow.
"""

from __future__ import annotations

from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.agents.tool_calling.registry import ToolMeta


def build_kb_chat_graph(
    *,
    chat_model: ChatOpenAI,
    tools: list[BaseTool],
    tool_meta_by_name: dict[str, ToolMeta],
    kb_chat_config: dict[str, bool] | None = None,
) -> KbChatAgenticGraph:
    return KbChatAgenticGraph(
        chat_model=chat_model,
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        kb_chat_config=kb_chat_config,
    )
