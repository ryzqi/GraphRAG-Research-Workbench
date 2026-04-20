"""普通代理构造器与 HITL 映射工具。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    SummarizationMiddleware,
)
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.checkpoint import CheckpointManager
from app.agents.tool_calling.utils import parse_mcp_tool_name

SUMMARY_TRIGGER_FRACTION = 0.7
SUMMARY_TRIGGER: tuple[Literal["fraction"], float] = (
    "fraction",
    SUMMARY_TRIGGER_FRACTION,
)
DEFAULT_SUMMARY_KEEP_MESSAGES = 20


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
            parsed = parse_mcp_tool_name(name)
            if parsed is not None:
                extension_id, raw_tool_name = parsed
                pending.append(
                    {
                        "extension_id": extension_id,
                        "extension_name": None,
                        "tool_name": raw_tool_name,
                        "args": args,
                        "is_builtin": False,
                    }
                )
                continue
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


def build_hitl_interrupt_on(
    tool_meta_by_name: dict[str, Any],
) -> dict[str, bool]:
    """构建 HITL interrupt_on 配置：仅拦截 MCP 扩展工具。"""
    interrupt_on: dict[str, bool] = {}
    for tool_name, meta in tool_meta_by_name.items():
        if bool(getattr(meta, "is_builtin", True)):
            continue
        interrupt_on[tool_name] = True
    return interrupt_on


def build_general_chat_agent(
    *,
    chat_model: BaseChatModel,
    tools: list[Any],
    system_prompt: str,
    summary_trigger: ContextSize | list[ContextSize],
    summary_keep_messages: int,
    summary_trim_tokens: int | None,
    tool_context_trigger_tokens: int | None,
    hitl_interrupt_on: Mapping[str, bool | InterruptOnConfig] | None = None,
):
    clear_tool_trigger = (
        tool_context_trigger_tokens
        if tool_context_trigger_tokens is not None and tool_context_trigger_tokens > 0
        else 100_000
    )
    middleware: list[Any] = [
        SummarizationMiddleware(
            model=chat_model,
            trigger=summary_trigger,
            keep=("messages", summary_keep_messages),
            trim_tokens_to_summarize=summary_trim_tokens,
        ),
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=clear_tool_trigger,
                    keep=3,
                    clear_tool_inputs=False,
                    placeholder="[cleared by context editing]",
                ),
            ],
        ),
    ]
    if hitl_interrupt_on:
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on=dict(hitl_interrupt_on),
                description_prefix="外部工具调用待审批",
            )
        )
    return create_agent(
        model=chat_model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=CheckpointManager.get_checkpointer(),
        middleware=middleware,
    )
