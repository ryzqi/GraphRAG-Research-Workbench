"""Helpers for KB chat runtime toggle resolution from graph state."""

from __future__ import annotations

from typing import Any

from app.core.settings import Settings


def _state_flag(
    state: dict[str, Any],
    *,
    key: str,
    default: bool,
) -> bool:
    runtime = state.get("runtime_config")
    if isinstance(runtime, dict):
        value = runtime.get(key)
        if isinstance(value, bool):
            return value
    return default


def query_rewrite_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="query_rewrite_enabled",
        default=bool(settings.retrieval_query_rewrite_enabled),
    )


def ambiguity_check_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="ambiguity_check_enabled",
        default=bool(settings.kb_chat_ambiguity_check_enabled),
    )


def decomposition_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="decomposition_enabled",
        default=bool(settings.kb_chat_decomposition_enabled),
    )


def multi_query_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="multi_query_enabled",
        default=bool(settings.kb_chat_multi_query_enabled),
    )


def hyde_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="hyde_enabled",
        default=bool(settings.kb_chat_hyde_enabled),
    )


def force_retrieve_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="force_retrieve_enabled",
        default=bool(settings.kb_chat_force_retrieve),
    )
