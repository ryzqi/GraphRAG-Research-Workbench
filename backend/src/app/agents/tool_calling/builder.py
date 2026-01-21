"""ToolNode/工具调用统一循环图构建器。

该构建器用于生成标准的：model -> (human_review?) -> tools -> model 循环图。
- model 节点：调用绑定工具的 ChatOpenAI，产生回答或 tool_calls。
- tools 节点：ToolNode 执行工具，追加 ToolMessage。
- human_review 节点：仅在 GENERAL_CHAT 中使用 interrupt 提供两阶段审批。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Sequence

from langchain.messages import AIMessage, SystemMessage, ToolMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from .registry import ToolMeta
from .utils import extract_pending_tool_calls


class ToolCallingGraphBuilder:
    """统一 ToolNode loop 构建器。"""

    def __init__(
        self,
        *,
        state_schema: type,
        chat_model: ChatOpenAI,
        tools: Sequence[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],
        require_human_review: bool = False,
        force_tool_flag_key: str | None = None,
        force_tool_name: str | None = None,
        messages_key: str = "messages",
    ) -> None:
        self._state_schema = state_schema
        self._tools = list(tools)
        self._tool_meta_by_name = tool_meta_by_name
        self._require_human_review = require_human_review
        self._force_tool_flag_key = force_tool_flag_key
        self._force_tool_name = force_tool_name
        self._messages_key = messages_key

        # ToolNode：统一工具执行与错误处理。
        self._tool_node = ToolNode(
            self._tools,
            handle_tool_errors=True,
            messages_key=messages_key,
        )

        # LLM：同一模型派生不同 tool_choice 版本。
        if self._tools:
            self._model_auto = chat_model.bind_tools(self._tools)
            self._model_no_tools = chat_model.bind_tools(self._tools, tool_choice="none")
            self._model_forced = (
                chat_model.bind_tools(
                    self._tools,
                    tool_choice={
                        "type": "function",
                        "function": {"name": force_tool_name},
                    },
                )
                if force_tool_name
                else None
            )
        else:
            self._model_auto = chat_model
            self._model_no_tools = chat_model
            self._model_forced = None

    def build(self) -> StateGraph:
        """构建 StateGraph。"""
        graph = StateGraph(self._state_schema)

        graph.add_node("model", self._model_node)
        graph.add_node("tools", self._tools_node)

        if self._require_human_review:
            graph.add_node("human_review", self._human_review_node)
            graph.add_node("model_no_tools", self._model_no_tools_node)

        graph.set_entry_point("model")

        if self._require_human_review:
            graph.add_conditional_edges(
                "model",
                self._route_after_model,
                {"human_review": "human_review", "tools": "tools", "end": END},
            )
            graph.add_conditional_edges(
                "human_review",
                self._route_after_review,
                {"tools": "tools", "model_no_tools": "model_no_tools"},
            )
            graph.add_edge("tools", "model")
            graph.add_edge("model_no_tools", END)
        else:
            graph.add_conditional_edges(
                "model",
                self._route_after_model,
                {"tools": "tools", "end": END},
            )
            graph.add_edge("tools", "model")

        return graph


    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _last_ai(messages: Sequence[object]) -> AIMessage | None:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg
        return None

    def _route_after_model(self, state: dict) -> str:
        messages = state.get(self._messages_key, [])
        last_ai = self._last_ai(messages if isinstance(messages, list) else [])
        if last_ai is None or not getattr(last_ai, "tool_calls", None):
            return "end"

        if self._require_human_review:
            pending = extract_pending_tool_calls(
                messages,
                self._tool_meta_by_name,
                external_only=True,
            )
            if pending:
                return "human_review"

        return "tools"

    def _route_after_review(self, state: dict) -> str:
        if state.get("human_approved"):
            return "tools"
        return "model_no_tools"

    async def _model_node(self, state: dict) -> dict[str, Any]:
        messages = state.get(self._messages_key, [])
        if not isinstance(messages, list):
            messages = []

        model = self._model_auto
        updates: dict[str, Any] = {}
        if (
            self._model_forced is not None
            and self._force_tool_flag_key
            and state.get(self._force_tool_flag_key)
        ):
            model = self._model_forced
            updates[self._force_tool_flag_key] = False

        start = time.perf_counter()
        ai_msg = await model.ainvoke(messages)
        latency_ms = int((time.perf_counter() - start) * 1000)

        stage_summaries = state.get("stage_summaries")
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}
        stage_summaries = {
            **stage_summaries,
            "model": {
                "latency_ms": latency_ms,
                "tool_calls": len(getattr(ai_msg, "tool_calls", None) or []),
                "completed_at": self._now_iso(),
            },
        }

        metrics = state.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}

        usage = getattr(ai_msg, "usage_metadata", None)
        if hasattr(usage, "model_dump"):
            usage_json = usage.model_dump()
        elif isinstance(usage, dict):
            usage_json = usage
        else:
            usage_json = None

        metrics = {
            **metrics,
            "llm": {
                "latency_ms": latency_ms,
                "usage": usage_json,
            },
        }

        pending_tool_calls = (
            extract_pending_tool_calls([ai_msg], self._tool_meta_by_name, external_only=True)
            if self._require_human_review
            else []
        )

        return {
            **updates,
            self._messages_key: [ai_msg],
            "pending_tool_calls": pending_tool_calls,
            "stage_summaries": stage_summaries,
            "metrics": metrics,
        }

    async def _tools_node(self, state: dict) -> dict[str, Any]:
        result = await self._tool_node.ainvoke(state)
        if not isinstance(result, dict):
            return {}

        new_messages = result.get(self._messages_key, [])
        tool_msgs = [m for m in new_messages if isinstance(m, ToolMessage)]
        succeeded = sum(1 for m in tool_msgs if getattr(m, "status", "success") == "success")

        stage_summaries = state.get("stage_summaries")
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}
        stage_summaries = {
            **stage_summaries,
            "tools": {
                "executed": len(tool_msgs),
                "succeeded": succeeded,
                "completed_at": self._now_iso(),
            },
        }

        return {
            **result,
            "stage_summaries": stage_summaries,
        }

    async def _human_review_node(self, state: dict) -> dict[str, Any]:
        messages = state.get(self._messages_key, [])
        if not isinstance(messages, list):
            messages = []

        pending = extract_pending_tool_calls(
            messages,
            self._tool_meta_by_name,
            external_only=True,
        )
        if not pending:
            return {"human_approved": True, "pending_tool_calls": []}

        human_response = interrupt(
            {
                "type": "tool_approval",
                "tools": pending,
                "message": "请审核以下工具调用",
            }
        )
        approved = (
            bool(human_response.get("approved", False))
            if isinstance(human_response, dict)
            else False
        )

        updates: dict[str, Any] = {
            "human_approved": approved,
            "pending_tool_calls": pending,
        }

        if not approved:
            # 生成“拒绝执行”的 ToolMessage，满足 tool_calls 协议，避免后续模型调用报错。
            last_ai = self._last_ai(messages)
            tool_calls = getattr(last_ai, "tool_calls", None) or []
            canceled: list[ToolMessage] = []
            for call in tool_calls:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
                if not name or not call_id:
                    continue
                meta = self._tool_meta_by_name.get(str(name))
                if meta is None or not meta.is_external:
                    continue
                canceled.append(
                    ToolMessage(
                        tool_call_id=str(call_id),
                        name=str(name),
                        content="用户拒绝执行外部工具调用。",
                        status="error",
                        additional_kwargs={"canceled": True},
                    )
                )

            updates[self._messages_key] = canceled

        return updates

    async def _model_no_tools_node(self, state: dict) -> dict[str, Any]:
        messages = state.get(self._messages_key, [])
        if not isinstance(messages, list):
            messages = []

        denial = SystemMessage(
            content="用户已拒绝外部工具调用，请直接回答，不要再次请求外部工具。"
        )

        start = time.perf_counter()
        ai_msg = await self._model_no_tools.ainvoke([*messages, denial])
        latency_ms = int((time.perf_counter() - start) * 1000)

        stage_summaries = state.get("stage_summaries")
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}
        stage_summaries = {
            **stage_summaries,
            "model_no_tools": {
                "latency_ms": latency_ms,
                "completed_at": self._now_iso(),
            },
        }

        return {
            self._messages_key: [denial, ai_msg],
            "stage_summaries": stage_summaries,
        }
