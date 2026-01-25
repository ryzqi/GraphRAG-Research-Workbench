"""知识库问答 LangGraph 实现（ToolNode + 工具调用）。

约束：KB_CHAT 必须至少执行一次 kb_retrieve，以确保回答可追溯证据。
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict, cast

from langchain.messages import AnyMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.message import add_messages
from langgraph.store.base import BaseStore

from app.agents.tool_calling.builder import ToolCallingGraphBuilder
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings


class KbChatState(TypedDict):
    """知识库问答状态（以 messages 为核心）。"""

    messages: Annotated[list[AnyMessage], add_messages]
    pending_tool_calls: list[dict]
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]
    force_kb_retrieve: bool


logger = logging.getLogger(__name__)


def build_kb_chat_graph(
    *,
    chat_model: ChatOpenAI,
    tools: list[BaseTool],
    tool_meta_by_name: dict[str, ToolMeta],
):
    """Build KB Chat graph according to KB_CHAT_FLOW_VERSION (with safe fallback)."""
    settings = get_settings()
    if settings.kb_chat_flow_version == "legacy":
        return KbChatGraph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
        )

    try:
        from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
    except ImportError:
        logger.warning("KB_CHAT_FLOW_VERSION=agentic 但 agentic 图未就绪，回退到 legacy。")
        return KbChatGraph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
        )

    try:
        return KbChatAgenticGraph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
        )
    except Exception:
        logger.exception("Agentic KB Chat 图初始化失败，回退到 legacy。")
        return KbChatGraph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
        )



class KbChatGraph:
    """知识库问答 LangGraph 图。"""

    def __init__(
        self,
        *,
        chat_model: ChatOpenAI,
        tools: list[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],
    ) -> None:
        builder = ToolCallingGraphBuilder(
            state_schema=KbChatState,
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            require_human_review=False,
            force_tool_flag_key="force_kb_retrieve",
            force_tool_name="kb_retrieve",
            messages_key="messages",
        )
        self._graph_builder = builder.build()

    def compile(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ):
        return self._graph_builder.compile(checkpointer=checkpointer, store=store)

    async def run(
        self,
        state: KbChatState,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ) -> dict[str, Any]:
        compiled = self.compile(checkpointer=checkpointer, store=store)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = await compiled.ainvoke(state, config)
        return cast(dict[str, Any], result)
