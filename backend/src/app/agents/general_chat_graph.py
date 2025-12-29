"""全能代理 LangGraph 实现。

将全能代理流程转换为 LangGraph 图，支持检查点持久化和 Human-in-the-loop。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_client import MCPClient, ToolDefinition
from app.models.tool_extension import ToolExtension
from app.prompts import get_prompt_loader


@dataclass
class GeneralChatState:
    """全能代理状态。"""

    question: str
    allow_external: bool = False
    history: list[LLMMessage] = field(default_factory=list)

    # 阶段输出
    tool_results: list[dict] = field(default_factory=list)
    answer: str = ""

    # Human-in-the-loop
    pending_tool_calls: list[dict] = field(default_factory=list)
    human_approved: bool | None = None

    # 元数据
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class GeneralChatGraph:
    """全能代理 LangGraph 图（支持 Human-in-the-loop）。"""

    def __init__(
        self,
        llm: LLMClient,
        mcp: MCPClient,
        extensions: list[ToolExtension],
        require_confirmation: bool = True,
    ) -> None:
        self._llm = llm
        self._mcp = mcp
        self._extensions = extensions
        self._require_confirmation = require_confirmation
        self._prompts = get_prompt_loader()
        self._graph_builder = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建代理图。"""
        graph = StateGraph(GeneralChatState)

        graph.add_node("plan_tools", self._plan_tools_node)
        graph.add_node("human_review", self._human_review_node)
        graph.add_node("execute_tools", self._execute_tools_node)
        graph.add_node("generate", self._generate_node)

        graph.set_entry_point("plan_tools")

        graph.add_conditional_edges("plan_tools", self._route_after_plan, {
            "human_review": "human_review",
            "execute_tools": "execute_tools",
            "generate": "generate",
        })
        graph.add_conditional_edges("human_review", self._route_after_review, {
            "execute_tools": "execute_tools",
            "generate": "generate",
        })
        graph.add_edge("execute_tools", "generate")
        graph.add_edge("generate", END)

        return graph

    def compile(self, checkpointer: BaseCheckpointSaver | None = None):
        """编译图。"""
        return self._graph_builder.compile(checkpointer=checkpointer)

    async def run(
        self,
        state: GeneralChatState,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> GeneralChatState:
        """执行代理流程。"""
        compiled = self.compile(checkpointer)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        return await compiled.ainvoke(state, config)

    def _route_after_plan(self, state: GeneralChatState) -> str:
        """规划后路由。"""
        if not state.pending_tool_calls:
            return "generate"
        if self._require_confirmation:
            return "human_review"
        return "execute_tools"

    def _route_after_review(self, state: GeneralChatState) -> str:
        """审核后路由。"""
        if state.human_approved:
            return "execute_tools"
        return "generate"

    async def _plan_tools_node(self, state: GeneralChatState) -> dict:
        """规划工具调用。"""
        if not state.allow_external or not self._extensions:
            return {"pending_tool_calls": []}

        # 收集所有可用工具
        all_tools: list[tuple[ToolExtension, ToolDefinition]] = []
        for ext in self._extensions:
            tools = await self._mcp.connect(
                str(ext.id), ext.transport.value, ext.endpoint, ext.scope
            )
            for tool in tools:
                all_tools.append((ext, tool))

        if not all_tools:
            return {"pending_tool_calls": []}

        # LLM 驱动工具选择
        selected = await self._select_tools_with_llm(state.question, all_tools)

        return {
            "pending_tool_calls": selected,
            "stage_summaries": {
                "plan_tools": {
                    "available_tools": len(all_tools),
                    "selected_tools": len(selected),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

    async def _select_tools_with_llm(
        self,
        question: str,
        tools: list[tuple[ToolExtension, ToolDefinition]],
    ) -> list[dict]:
        """LLM 驱动工具选择和参数生成。"""
        if not tools:
            return []

        tool_desc = "\n".join(
            f"{i}. {t.name}: {t.description or '无描述'}"
            for i, (_, t) in enumerate(tools)
        )

        prompt = self._prompts.render(
            "general_chat/tool_selection",
            question=question,
            tool_desc=tool_desc,
        )

        try:
            response = await self._llm.chat(
                messages=[LLMMessage(role="user", content=prompt)]
            )

            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0]

            selections = json.loads(response)
            if not isinstance(selections, list):
                return []

            result = []
            for sel in selections:
                idx = sel.get("index", -1)
                args = sel.get("args", {})
                if 0 <= idx < len(tools):
                    ext, tool = tools[idx]
                    result.append({
                        "extension_id": str(ext.id),
                        "extension_name": ext.name,
                        "tool_name": tool.name,
                        "args": args,
                    })

            return result
        except (json.JSONDecodeError, KeyError):
            return []

    async def _human_review_node(self, state: GeneralChatState) -> dict:
        """人工审核节点（使用 interrupt）。"""
        if state.pending_tool_calls and self._require_confirmation:
            human_response = interrupt({
                "type": "tool_approval",
                "tools": state.pending_tool_calls,
                "message": "请审核以下工具调用",
            })
            return {"human_approved": human_response.get("approved", False)}
        return {"human_approved": True}

    async def _execute_tools_node(self, state: GeneralChatState) -> dict:
        """执行工具调用。"""
        if not state.human_approved:
            return {"tool_results": []}

        results = []
        for tool_call in state.pending_tool_calls:
            call_result = await self._mcp.call_tool(
                tool_call["extension_id"],
                tool_call["tool_name"],
                tool_call["args"],
            )
            results.append({
                "tool_name": tool_call["tool_name"],
                "extension_name": tool_call["extension_name"],
                "success": call_result.success,
                "output": call_result.output if call_result.success else call_result.error,
            })

        return {
            "tool_results": results,
            "stage_summaries": {
                **state.stage_summaries,
                "execute_tools": {
                    "executed": len(results),
                    "succeeded": sum(1 for r in results if r["success"]),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

    async def _generate_node(self, state: GeneralChatState) -> dict:
        """生成回答。"""
        system_prompt = self._build_system_prompt(state)
        messages = [
            LLMMessage(role="system", content=system_prompt),
            *state.history,
            LLMMessage(role="user", content=state.question),
        ]

        response = await self._llm.chat_with_metrics(messages=messages)

        return {
            "answer": response.content,
            "stage_summaries": {
                **state.stage_summaries,
                "generation": {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

    def _build_system_prompt(self, state: GeneralChatState) -> str:
        """构建系统提示词。"""
        base = self._prompts.render("general_chat/system")

        if state.tool_results:
            tool_context = "\n".join(
                f"- {r['tool_name']} ({r['extension_name']}): "
                f"{'成功' if r['success'] else '失败'} - {r['output']}"
                for r in state.tool_results
            )
            base += f"\n\n工具调用结果：\n{tool_context}"

        return base
