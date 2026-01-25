"""Tool-calling loop nodes for KB Chat agentic graph.

This is a lightly customized version of ToolCallingGraphBuilder:
- Adds KB chat budget accounting (total_rounds) and budget-based ForceExit
- Keeps update shapes compatible with existing streaming/service plumbing
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from langchain.messages import AIMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from app.core.settings import Settings

from .budget import budget_exceeded, now_iso


def _last_ai(messages: Sequence[object]) -> AIMessage | None:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg
    return None


def _extract_usage_json(ai_msg: AIMessage) -> dict[str, Any] | None:
    usage = getattr(ai_msg, "usage_metadata", None)
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return None


class ToolLoop:
    def __init__(
        self,
        *,
        settings: Settings,
        chat_model: ChatOpenAI,
        tools: Sequence[BaseTool],
        force_tool_name: str | None = None,
        messages_key: str = "messages",
    ) -> None:
        self._settings = settings
        self._tools = list(tools)
        self._messages_key = messages_key
        self._force_tool_name = force_tool_name

        self._tool_node = ToolNode(
            self._tools,
            handle_tool_errors=True,
            messages_key=messages_key,
        )

        if self._tools:
            self._model_auto = chat_model.bind_tools(self._tools)
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
            self._model_forced = None

    def route_after_model(self, state: dict) -> str:
        messages = state.get(self._messages_key, [])
        last_ai = _last_ai(messages if isinstance(messages, list) else [])
        if last_ai is None or not getattr(last_ai, "tool_calls", None):
            return "end"

        exceeded, _reason = budget_exceeded(state, self._settings)
        if exceeded:
            return "force_exit"
        return "tools"

    async def model_node(self, state: dict) -> dict[str, Any]:
        messages = state.get(self._messages_key, [])
        if not isinstance(messages, list):
            messages = []

        # Budget accounting: treat each model execution as one "round".
        loop_counts = state.get("loop_counts")
        if not isinstance(loop_counts, dict):
            loop_counts = {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
        loop_counts = {
            **loop_counts,
            "total_rounds": int(loop_counts.get("total_rounds") or 0) + 1,
        }

        model = self._model_auto
        updates: dict[str, Any] = {"loop_counts": loop_counts}
        if (
            self._model_forced is not None
            and self._force_tool_name
            and state.get("force_kb_retrieve")
        ):
            model = self._model_forced
            updates["force_kb_retrieve"] = False

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
                "completed_at": now_iso(),
            },
        }

        metrics = state.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        metrics = {
            **metrics,
            "llm": {
                "latency_ms": latency_ms,
                "usage": _extract_usage_json(ai_msg),
            },
        }

        return {
            **updates,
            self._messages_key: [ai_msg],
            "pending_tool_calls": [],
            "stage_summaries": stage_summaries,
            "metrics": metrics,
        }

    async def tools_node(self, state: dict) -> dict[str, Any]:
        result = await self._tool_node.ainvoke(state)
        if not isinstance(result, dict):
            return {}

        stage_summaries = result.get("stage_summaries")
        if not isinstance(stage_summaries, dict):
            stage_summaries = state.get("stage_summaries")
            if not isinstance(stage_summaries, dict):
                stage_summaries = {}
        stage_summaries = {
            **stage_summaries,
            "tools": {
                "completed_at": now_iso(),
            },
        }

        return {
            **result,
            "stage_summaries": stage_summaries,
        }


def force_exit_node(state: dict, settings: Settings) -> dict[str, Any]:
    """Produce a final assistant message when exiting due to clarify/budget."""
    reflection = state.get("reflection")
    action = reflection.get("action") if isinstance(reflection, dict) else None

    reason = ""
    if action == "clarify":
        reason = "clarify"
    else:
        exceeded, why = budget_exceeded(state, settings)
        reason = why if exceeded else "force_exit"

    final_answer = state.get("final_answer")
    if not isinstance(final_answer, str) or not final_answer.strip():
        # Prefer the latest draft (agentic reflection path) before falling back to messages.
        draft_answer = state.get("draft_answer")
        if isinstance(draft_answer, str) and draft_answer.strip():
            final_answer = draft_answer

        if action == "clarify":
            final_answer = "为了更准确地回答，请补充必要信息后再提问。"
        else:
            # Prefer "current best" only when we know this run executed a model/generator step,
            # otherwise we might accidentally return a previous history AI message.
            stage_summaries = state.get("stage_summaries")
            ran_model = isinstance(stage_summaries, dict) and (
                "model" in stage_summaries or "generator" in stage_summaries
            )
            if ran_model:
                messages = state.get("messages")
                last_ai = _last_ai(messages if isinstance(messages, list) else [])
                content = getattr(last_ai, "content", None) if last_ai is not None else None
                if isinstance(content, str) and content.strip():
                    final_answer = content

            if not isinstance(final_answer, str) or not final_answer.strip():
                final_answer = "根据现有资料无法回答该问题（已停止重试）。"

    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "force_exit": {
            "reason": reason,
            "completed_at": now_iso(),
        },
    }

    return {
        "messages": [AIMessage(content=final_answer)],
        "final_answer": final_answer,
        "stage_summaries": stage_summaries,
    }
