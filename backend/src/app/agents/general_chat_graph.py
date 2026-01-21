"""普通代理 LangGraph 实现（ToolNode + OpenAI 风格工具调用）。

- 使用 ToolCallingGraphBuilder 构建标准循环：model -> (human_review?) -> tools -> model
- human_review 通过 interrupt 实现两阶段审批（由上层 service 负责返回/恢复）

说明：旧的“索引 JSON 选择工具”提示词仍保留以便回滚/对照，但不再用于默认链路。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict, cast

from langchain.messages import AnyMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.message import add_messages

from app.agents.tool_calling.builder import ToolCallingGraphBuilder
from app.agents.tool_calling.registry import ToolMeta


class GeneralChatState(TypedDict):
    """普通代理状态（以 messages 为核心）。"""

    messages: Annotated[list[AnyMessage], add_messages]
    pending_tool_calls: list[dict]
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]
    human_approved: bool | None



class GeneralChatGraph:
    """普通代理 LangGraph 图（支持 Human-in-the-loop）。"""

    def __init__(
        self,
        *,
        chat_model: ChatOpenAI,
        tools: list[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],
        require_confirmation: bool = True,
    ) -> None:
        builder = ToolCallingGraphBuilder(
            state_schema=GeneralChatState,
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            require_human_review=require_confirmation,
            messages_key="messages",
        )
        self._graph_builder = builder.build()

    def compile(self, checkpointer: BaseCheckpointSaver | None = None):
        """编译图。"""
        return self._graph_builder.compile(checkpointer=checkpointer)

    async def run(
        self,
        state: GeneralChatState,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> dict[str, Any]:
        """执行代理流程。"""
        compiled = self.compile(checkpointer)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = await compiled.ainvoke(state, config)
        return cast(dict[str, Any], result)
