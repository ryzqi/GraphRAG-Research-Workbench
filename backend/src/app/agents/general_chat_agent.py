"""普通代理构造器与 HITL 映射工具。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    LLMToolSelectorMiddleware,
    SummarizationMiddleware,
)
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.checkpoint import CheckpointManager
from app.core.pii import build_pii_middleware
from app.core.settings import Settings
from app.agents.tool_selection import build_tool_selector_middleware
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
    tool_selector_enabled: bool = True,
    tool_selector_trigger_tool_count: int = 10,
    tool_selector_max_tools: int = 5,
    tool_selector_model_id: str | None = None,
    tool_selector_use_previous_response_id: bool | None = None,
    tool_selector_model: BaseChatModel | None = None,
    tool_selector_always_include: list[str] | None = None,
    pii_middleware_enabled: bool = True,
    pii_redaction_strategy: str = "redact",
    pii_apply_to_tool_results: bool = False,
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
    selector_settings = Settings(
        TOOL_SELECTOR_ENABLED=tool_selector_enabled,
        TOOL_SELECTOR_TRIGGER_TOOL_COUNT=tool_selector_trigger_tool_count,
        TOOL_SELECTOR_MAX_TOOLS=tool_selector_max_tools,
        TOOL_SELECTOR_MODEL_ID=tool_selector_model_id,
        TOOL_SELECTOR_ALWAYS_INCLUDE=tool_selector_always_include or [],
    )
    middleware.extend(
        build_tool_selector_middleware(
            settings=selector_settings,
            tools=tools,
            use_previous_response_id=tool_selector_use_previous_response_id,
            always_include=tool_selector_always_include or [],
        )
        if tool_selector_model is None
        else [
            LLMToolSelectorMiddleware(
                model=tool_selector_model,
                max_tools=tool_selector_max_tools,
                always_include=tool_selector_always_include or [],
            )
        ]
        if tool_selector_enabled and len(tools) > tool_selector_trigger_tool_count
        else []
    )
    pii_settings = Settings(
        PII_MIDDLEWARE_ENABLED=pii_middleware_enabled,
        PII_REDACTION_STRATEGY=pii_redaction_strategy,
        PII_APPLY_TO_TOOL_RESULTS=pii_apply_to_tool_results,
    )
    middleware.extend(build_pii_middleware(settings=pii_settings))
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
