"""Anthropic prompt caching middleware 装配。"""

from __future__ import annotations

from typing import Any, Literal, cast

from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

from app.core.settings import Settings


def build_anthropic_prompt_caching_middleware(*, settings: Settings) -> list[Any]:
    """构建 Anthropic Prompt Caching middleware。"""

    if not bool(getattr(settings, "anthropic_prompt_caching_enabled", True)):
        return []

    ttl = cast(
        Literal["5m", "1h"],
        getattr(settings, "anthropic_prompt_cache_ttl", "5m"),
    )
    return [
        AnthropicPromptCachingMiddleware(
            ttl=ttl,
            min_messages_to_cache=int(
                getattr(settings, "anthropic_prompt_cache_min_messages", 0)
            ),
            unsupported_model_behavior="ignore",
        )
    ]
