"""KB Chat 输出 token 配额解析。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.settings import Settings

_DRAFT_COMPLEXITY_MULTIPLIERS = {
    "simple": 1.0,
    "moderate": 1.25,
    "complex": 1.5,
}


def resolve_kb_chat_draft_max_tokens(
    complexity_level: str,
    settings: Settings,
) -> int:
    normalized = str(complexity_level).strip().lower()
    if normalized not in _DRAFT_COMPLEXITY_MULTIPLIERS:
        raise ValueError(
            f"Unsupported KB Chat complexity_level for draft max tokens: {complexity_level!r}"
        )
    return int(
        settings.kb_chat_draft_max_tokens
        * _DRAFT_COMPLEXITY_MULTIPLIERS[normalized]
    )


def resolve_kb_chat_draft_max_tokens_from_state(
    state: Mapping[str, Any],
    *,
    settings: Settings,
) -> int:
    complexity_level = state.get("complexity_level")
    if not isinstance(complexity_level, str) or not complexity_level.strip():
        raise ValueError("Missing KB Chat complexity_level for draft max tokens")
    return resolve_kb_chat_draft_max_tokens(complexity_level, settings)


def resolve_kb_chat_repair_max_tokens(settings: Settings) -> int:
    return int(settings.kb_chat_repair_max_tokens)


def resolve_kb_chat_plain_fallback_max_tokens(settings: Settings) -> int:
    return int(settings.kb_chat_plain_fallback_max_tokens)
