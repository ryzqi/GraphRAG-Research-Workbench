"""Agent 模型调用限流与降级 middleware 装配。"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import ModelCallLimitMiddleware, ModelFallbackMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.settings import Settings
from app.integrations.chat_model_factory import create_fallback_chat_model


def resolve_fallback_chat_model(
    *,
    settings: Settings,
    fallback_model_id: str | None,
    use_previous_response_id: bool | None,
) -> BaseChatModel | None:
    if not isinstance(fallback_model_id, str) or not fallback_model_id.strip():
        return None
    return create_fallback_chat_model(
        fallback_model_id=fallback_model_id.strip(),
        settings=settings,
        use_previous_response_id=use_previous_response_id,
    )


def build_agent_model_safety_middleware(
    *,
    settings: Settings,
    thread_limit_setting: str,
    run_limit_setting: str,
    fallback_model_id_setting: str,
    use_previous_response_id: bool | None,
) -> list[Any]:
    middleware: list[Any] = []
    thread_limit = getattr(settings, thread_limit_setting)
    run_limit = getattr(settings, run_limit_setting)
    if thread_limit is not None or run_limit is not None:
        middleware.append(
            ModelCallLimitMiddleware(
                thread_limit=thread_limit,
                run_limit=run_limit,
                exit_behavior="end",
            )
        )

    fallback_model = resolve_fallback_chat_model(
        settings=settings,
        fallback_model_id=getattr(settings, fallback_model_id_setting),
        use_previous_response_id=use_previous_response_id,
    )
    if fallback_model is not None:
        middleware.append(ModelFallbackMiddleware(fallback_model))
    return middleware
