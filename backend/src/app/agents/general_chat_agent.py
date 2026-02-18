"""普通代理构造器与 HITL 映射工具。"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_openai import ChatOpenAI

from app.core.checkpoint import CheckpointManager

SUMMARY_TRIGGER_FRACTION = 0.7
SUMMARY_TRIGGER = ("fraction", SUMMARY_TRIGGER_FRACTION)
SUMMARY_KEEP = ("messages", 20)
HITL_REJECT_MESSAGE = "用户拒绝执行外部工具调用。"


def build_pending_tool_calls(
    action_requests: list[dict[str, Any]],
    tool_meta_by_name: dict[str, Any],
) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for item in action_requests:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        args = item.get("arguments")
        if not isinstance(args, dict):
            args = item.get("args")
        if not isinstance(args, dict):
            args = {}

        meta = tool_meta_by_name.get(name)
        if meta is None:
            pending.append(
                {
                    "extension_id": "unknown",
                    "extension_name": None,
                    "tool_name": name,
                    "args": args,
                    "is_builtin": False,
                }
            )
            continue

        pending.append(
            {
                "extension_id": meta.extension_id,
                "extension_name": meta.extension_name,
                "tool_name": meta.raw_tool_name,
                "args": args,
                "is_builtin": meta.is_builtin,
            }
        )
    return pending


def build_hitl_decisions(action_count: int, approved: bool) -> list[dict[str, Any]]:
    if action_count <= 0:
        return []
    if approved:
        return [{"type": "approve"} for _ in range(action_count)]
    return [
        {"type": "reject", "message": HITL_REJECT_MESSAGE} for _ in range(action_count)
    ]


def build_general_chat_agent(
    *,
    chat_model: ChatOpenAI,
    tools: list[Any],
    system_prompt: str,
    summary_trigger: tuple[str, int] | tuple[str, float],
):
    return create_agent(
        model=chat_model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=CheckpointManager.get_checkpointer(),
        middleware=[
            SummarizationMiddleware(
                model=chat_model,
                trigger=summary_trigger,
                keep=SUMMARY_KEEP,
            )
        ],
    )
