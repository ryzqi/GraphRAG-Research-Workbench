"""全能代理 LangGraph 实现。

将全能代理流程转换为 LangGraph 图，支持检查点持久化和 Human-in-the-loop。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.tools.web_search import build_web_search_tool
from app.core.settings import Settings
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_client import MCPClient, ToolDefinition
from app.models.tool_extension import ToolExtension
from app.prompts import get_prompt_loader
from app.services.context_builder import ContextBuilder


@dataclass
class GeneralChatState:
    """全能代理状态。"""

    question: str
    allow_external: bool = False
    history: list[LLMMessage] = field(default_factory=list)
    summary: str | None = None

    # 阶段输出
    tool_results: list[dict] = field(default_factory=list)
    answer: str = ""

    # Human-in-the-loop
    pending_tool_calls: list[dict] = field(default_factory=list)
    human_approved: bool | None = None

    # 元数据
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class GeneralChatGraph:
    """全能代理 LangGraph 图（支持 Human-in-the-loop）。"""

    def __init__(
        self,
        llm: LLMClient,
        mcp: MCPClient,
        extensions: list[ToolExtension],
        require_confirmation: bool = True,
        context_builder: ContextBuilder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm
        self._mcp = mcp
        self._extensions = extensions
        self._require_confirmation = require_confirmation
        self._prompts = get_prompt_loader()
        self._graph_builder = self._build_graph()
        self._context_builder = context_builder
        self._settings = settings
        self._builtin_tools: list = []

    def _build_graph(self) -> StateGraph:
        """构建代理图。"""
        graph = StateGraph(GeneralChatState)

        graph.add_node("plan_tools", self._plan_tools_node)
        graph.add_node("human_review", self._human_review_node)
        graph.add_node("execute_tools", self._execute_tools_node)
        graph.add_node("generate", self._generate_node)

        graph.set_entry_point("plan_tools")

        graph.add_conditional_edges(
            "plan_tools",
            self._route_after_plan,
            {
                "human_review": "human_review",
                "execute_tools": "execute_tools",
                "generate": "generate",
            },
        )
        graph.add_conditional_edges(
            "human_review",
            self._route_after_review,
            {
                "execute_tools": "execute_tools",
                "generate": "generate",
            },
        )
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
    ) -> dict[str, Any]:
        """执行代理流程。

        注意：LangGraph 的 `ainvoke` 返回值在类型标注上通常是 `Any`/`dict`，并且会包含
        `__interrupt__` 等运行期字段，因此这里统一约定返回 `dict[str, Any]` 供上层服务处理。
        """
        compiled = self.compile(checkpointer)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = await compiled.ainvoke(state, config)
        return cast(dict[str, Any], result)

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
        if not state.allow_external:
            return {"pending_tool_calls": []}

        # 收集内置工具
        builtin_tools: list[tuple[str, str, str]] = []
        if self._settings and self._settings.web_search_api_key:
            web_tool = build_web_search_tool(self._settings)
            builtin_tools.append(("builtin", "web_search", web_tool.description))

        # 收集 MCP 扩展工具
        all_tools: list[tuple[ToolExtension, ToolDefinition]] = []
        for ext in self._extensions:
            tools = await self._mcp.connect(
                str(ext.id), ext.transport.value, ext.endpoint, ext.scope
            )
            for tool in tools:
                all_tools.append((ext, tool))

        if not all_tools and not builtin_tools:
            return {"pending_tool_calls": []}

        # 合并工具描述用于 LLM 选择
        combined_tools = []
        for ext_id, name, desc in builtin_tools:
            combined_tools.append((ext_id, name, desc))
        for ext, tool in all_tools:
            combined_tools.append(
                (str(ext.id), tool.name, tool.description or "无描述")
            )

        # LLM 驱动工具选择
        selected = await self._select_tools_with_llm(
            state.question, combined_tools, all_tools
        )

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
        combined_tools: list[tuple[str, str, str]],
        mcp_tools: list[tuple[ToolExtension, ToolDefinition]],
    ) -> list[dict]:
        """LLM 驱动工具选择和参数生成。"""
        if not combined_tools:
            return []

        tool_desc = "\n".join(
            f"{i}. {name}: {desc}" for i, (_, name, desc) in enumerate(combined_tools)
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
                if not isinstance(sel, dict):
                    continue
                try:
                    idx = int(sel.get("index", -1))
                except (TypeError, ValueError):
                    continue
                args = sel.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                if 0 <= idx < len(combined_tools):
                    ext_id, name, _ = combined_tools[idx]
                    if ext_id == "builtin":
                        result.append(
                            {
                                "extension_id": "builtin",
                                "extension_name": "内置工具",
                                "tool_name": name,
                                "args": args,
                                "is_builtin": True,
                            }
                        )
                    else:
                        # 查找对应的 MCP 扩展
                        mcp_idx = idx - sum(
                            1 for e, _, _ in combined_tools[:idx] if e == "builtin"
                        )
                        if 0 <= mcp_idx < len(mcp_tools):
                            ext, tool = mcp_tools[mcp_idx]
                            result.append(
                                {
                                    "extension_id": str(ext.id),
                                    "extension_name": ext.name,
                                    "tool_name": tool.name,
                                    "args": args,
                                    "is_builtin": False,
                                }
                            )

            return result
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return []

    async def _human_review_node(self, state: GeneralChatState) -> dict:
        """人工审核节点（使用 interrupt）。"""
        if state.pending_tool_calls and self._require_confirmation:
            human_response = interrupt(
                {
                    "type": "tool_approval",
                    "tools": state.pending_tool_calls,
                    "message": "请审核以下工具调用",
                }
            )
            return {"human_approved": human_response.get("approved", False)}
        return {"human_approved": True}

    async def _execute_tools_node(self, state: GeneralChatState) -> dict:
        """执行工具调用。"""
        if not state.human_approved:
            return {"tool_results": []}

        results = []
        for tool_call in state.pending_tool_calls:
            is_builtin = tool_call.get("is_builtin", False)

            if is_builtin and tool_call["tool_name"] == "web_search":
                # 执行内置 Web 搜索工具
                if self._settings and self._settings.web_search_api_key:
                    web_tool = build_web_search_tool(self._settings)
                    try:
                        output = await web_tool.ainvoke(tool_call["args"])
                        results.append(
                            {
                                "extension_id": tool_call.get(
                                    "extension_id", "builtin"
                                ),
                                "tool_name": tool_call["tool_name"],
                                "extension_name": tool_call["extension_name"],
                                "args": tool_call.get("args", {}),
                                "is_builtin": True,
                                "success": True,
                                "output": output,
                            }
                        )
                    except Exception as e:
                        results.append(
                            {
                                "extension_id": tool_call.get(
                                    "extension_id", "builtin"
                                ),
                                "tool_name": tool_call["tool_name"],
                                "extension_name": tool_call["extension_name"],
                                "args": tool_call.get("args", {}),
                                "is_builtin": True,
                                "success": False,
                                "output": str(e),
                            }
                        )
                else:
                    results.append(
                        {
                            "extension_id": tool_call.get("extension_id", "builtin"),
                            "tool_name": tool_call["tool_name"],
                            "extension_name": tool_call["extension_name"],
                            "args": tool_call.get("args", {}),
                            "is_builtin": True,
                            "success": False,
                            "output": "未配置 WEB_SEARCH_API_KEY，无法执行内置工具 web_search",
                        }
                    )
            else:
                # 执行 MCP 扩展工具
                call_result = await self._mcp.call_tool(
                    tool_call["extension_id"],
                    tool_call["tool_name"],
                    tool_call["args"],
                )
                results.append(
                    {
                        "extension_id": tool_call.get("extension_id"),
                        "tool_name": tool_call["tool_name"],
                        "extension_name": tool_call["extension_name"],
                        "args": tool_call.get("args", {}),
                        "is_builtin": False,
                        "success": call_result.success,
                        "output": call_result.output
                        if call_result.success
                        else call_result.error,
                    }
                )

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
        if self._context_builder is None:
            tool_context = ""
            if state.tool_results:
                tool_context = "\n".join(
                    f"- {r['tool_name']} ({r['extension_name']}): "
                    f"{'成功' if r['success'] else '失败'} - {r['output']}"
                    for r in state.tool_results
                )
            system_prompt = self._build_system_prompt(tool_context)
            messages = [
                LLMMessage(role="system", content=system_prompt),
                *state.history,
                LLMMessage(role="user", content=state.question),
            ]
            context_metrics = {}
        else:
            tool_context, tool_usage, tool_truncation = (
                self._context_builder.build_tool_context(state.tool_results)
            )
            system_prompt = self._build_system_prompt(tool_context)
            history_messages, history_usage, history_truncation = (
                self._context_builder.build_history_messages(
                    history=state.history, summary_text=state.summary
                )
            )
            messages = self._context_builder.build_messages(
                system_prompt=system_prompt,
                history_messages=history_messages,
                question=state.question,
            )
            context_metrics = self._context_builder.build_metrics(
                history_usage=history_usage,
                history_truncation=history_truncation,
                tool_usage=tool_usage,
                tool_truncation=tool_truncation,
            )

        response = await self._llm.chat_with_metrics(messages=messages)

        return {
            "answer": response.content,
            "stage_summaries": {
                **state.stage_summaries,
                "generation": {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            },
            "metrics": {
                **state.metrics,
                "context": context_metrics,
            },
        }

    def _build_system_prompt(self, tool_context: str) -> str:
        """构建系统提示词。"""
        base = self._prompts.render("general_chat/system")

        if tool_context:
            base += f"\n\n工具调用结果：\n{tool_context}"

        return base
