from __future__ import annotations

from typing import Annotated, Any, TypedDict

import pytest
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import BaseTool, tool as lc_tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langgraph.types import Command

from app.agents.tool_calling.builder import ToolCallingGraphBuilder
from app.agents.tool_calling.registry import ToolMeta


class FakeBoundModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)

    async def ainvoke(self, _messages: list[AnyMessage]) -> AIMessage:
        return self._responses.pop(0)


class FakeChatModel:
    def __init__(
        self, *, auto_responses: list[AIMessage], no_tools_responses: list[AIMessage]
    ) -> None:
        self._auto = FakeBoundModel(auto_responses)
        self._no_tools = FakeBoundModel(no_tools_responses)

    def bind_tools(self, _tools, tool_choice=None):
        if tool_choice == "none":
            return self._no_tools
        return self._auto


class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    pending_tool_calls: list[dict]
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]
    human_approved: bool | None


def _tool_meta() -> dict[str, ToolMeta]:
    return {
        "web_search": ToolMeta(
            tool_name="web_search",
            raw_tool_name="web_search",
            extension_id="builtin",
            extension_name="内置工具",
            is_builtin=True,
            is_external=True,
        )
    }


def _web_search_tool() -> BaseTool:
    async def _web_search(q: str) -> str:
        return f"search:{q}"

    return lc_tool(
        "web_search",
        description="demo",
    )(_web_search)


@pytest.mark.asyncio
async def test_tool_calling_interrupt_and_resume_approved_true() -> None:
    chat_model = FakeChatModel(
        auto_responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "web_search", "args": {"q": "x"}, "id": "call_1"}
                ],
            ),
            AIMessage(content="final"),
        ],
        no_tools_responses=[AIMessage(content="unused")],
    )

    builder = ToolCallingGraphBuilder(
        state_schema=GraphState,
        chat_model=chat_model,
        tools=[_web_search_tool()],
        tool_meta_by_name=_tool_meta(),
        require_human_review=True,
        messages_key="messages",
    )
    compiled = builder.build().compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    state: GraphState = {
        "messages": [SystemMessage(content="sys"), HumanMessage(content="hi")],
        "pending_tool_calls": [],
        "stage_summaries": {},
        "metrics": {},
        "human_approved": None,
    }

    first = await compiled.ainvoke(state, config)
    assert first.get("__interrupt__")
    assert first.get("pending_tool_calls")

    second = await compiled.ainvoke(Command(resume={"approved": True}), config)
    assert not second.get("__interrupt__")

    messages = second.get("messages") or []
    assert any(
        isinstance(m, ToolMessage) and str(m.content) == "search:x" for m in messages
    )
    assert any(isinstance(m, AIMessage) and str(m.content) == "final" for m in messages)


@pytest.mark.asyncio
async def test_tool_calling_interrupt_and_resume_denied() -> None:
    chat_model = FakeChatModel(
        auto_responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "web_search", "args": {"q": "x"}, "id": "call_1"}
                ],
            ),
        ],
        no_tools_responses=[AIMessage(content="no tools answer")],
    )

    builder = ToolCallingGraphBuilder(
        state_schema=GraphState,
        chat_model=chat_model,
        tools=[_web_search_tool()],
        tool_meta_by_name=_tool_meta(),
        require_human_review=True,
        messages_key="messages",
    )
    compiled = builder.build().compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    state: GraphState = {
        "messages": [SystemMessage(content="sys"), HumanMessage(content="hi")],
        "pending_tool_calls": [],
        "stage_summaries": {},
        "metrics": {},
        "human_approved": None,
    }

    first = await compiled.ainvoke(state, config)
    assert first.get("__interrupt__")

    second = await compiled.ainvoke(Command(resume={"approved": False}), config)
    messages = second.get("messages") or []

    assert any(
        isinstance(m, ToolMessage)
        and getattr(m, "status", None) == "error"
        and m.additional_kwargs.get("canceled") is True
        for m in messages
    )
    assert not any(isinstance(m, ToolMessage) and str(m.content).startswith("search:") for m in messages)
    assert any(isinstance(m, AIMessage) and str(m.content) == "no tools answer" for m in messages)
