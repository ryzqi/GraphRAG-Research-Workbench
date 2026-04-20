"""工具选择 middleware 装配。"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import LLMToolSelectorMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.settings import Settings
from app.integrations.chat_model_factory import create_fallback_chat_model


def resolve_tool_selector_model(
    *,
    settings: Settings,
    use_previous_response_id: bool | None,
) -> BaseChatModel | None:
    model_id = str(getattr(settings, "tool_selector_model_id", "") or "").strip()
    if not model_id:
        return None
    return create_fallback_chat_model(
        fallback_model_id=model_id,
        settings=settings,
        use_previous_response_id=use_previous_response_id,
    )


def build_tool_selector_middleware(
    *,
    settings: Settings,
    tools: list[Any],
    use_previous_response_id: bool | None,
    always_include: list[str] | None = None,
) -> list[Any]:
    if not bool(getattr(settings, "tool_selector_enabled", True)):
        return []
    trigger_count = int(getattr(settings, "tool_selector_trigger_tool_count", 10) or 10)
    if len(tools) <= trigger_count:
        return []

    selector_model = resolve_tool_selector_model(
        settings=settings,
        use_previous_response_id=use_previous_response_id,
    )
    selected_always_include = always_include
    if selected_always_include is None:
        selected_always_include = list(
            getattr(settings, "tool_selector_always_include", []) or []
        )

    return [
        LLMToolSelectorMiddleware(
            model=selector_model,
            max_tools=int(getattr(settings, "tool_selector_max_tools", 5) or 5),
            always_include=selected_always_include,
        )
    ]
