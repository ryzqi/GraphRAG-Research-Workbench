"""Helpers for KB chat runtime parameter resolution from graph state."""

from __future__ import annotations

from typing import Any

from app.core.settings import Settings


def _state_int(
    state: dict[str, Any],
    *,
    key: str,
    default: int,
) -> int:
    runtime = state.get("runtime_config")
    if isinstance(runtime, dict):
        value = runtime.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return int(default)


def _state_float(
    state: dict[str, Any],
    *,
    key: str,
    default: float,
) -> float:
    runtime = state.get("runtime_config")
    if isinstance(runtime, dict):
        value = runtime.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(default)


def normalize_alias_max(_: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(8, int(getattr(settings, "kb_chat_normalize_alias_max", 4))),
    )


def normalize_timeout_seconds(_: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        float(getattr(settings, "kb_chat_normalize_timeout_seconds", 0.8)),
    )


def entity_expand_max_candidates(state: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(
            12,
            _state_int(
                state,
                key="entity_expand_max_candidates",
                default=int(getattr(settings, "kb_chat_entity_expand_max_candidates", 8)),
            ),
        ),
    )


def entity_expand_max_variants(state: dict[str, Any], settings: Settings) -> int:
    max_candidates = entity_expand_max_candidates(state, settings)
    return max(
        1,
        min(
            max_candidates,
            _state_int(
                state,
                key="entity_expand_max_variants",
                default=int(getattr(settings, "kb_chat_entity_expand_max_variants", 6)),
            ),
        ),
    )


def entity_expand_min_confidence(state: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        min(
            1.0,
            _state_float(
                state,
                key="entity_expand_min_confidence",
                default=float(
                    getattr(settings, "kb_chat_entity_expand_min_confidence", 0.55)
                ),
            ),
        ),
    )


def entity_expand_timeout_seconds(state: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        min(
            5.0,
            _state_float(
                state,
                key="entity_expand_timeout_seconds",
                default=float(
                    getattr(settings, "kb_chat_entity_expand_timeout_seconds", 1.2)
                ),
            ),
        ),
    )


def retrieval_top_k(state: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        _state_int(
            state,
            key="retrieval_top_k",
            default=int(settings.retrieval_default_top_k),
        ),
    )


def parallel_retrieval_min_queries(_: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(8, int(getattr(settings, "kb_chat_parallel_retrieval_min_queries", 2))),
    )


def parallel_retrieval_max_branches(_: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(12, int(getattr(settings, "kb_chat_parallel_retrieval_max_branches", 6))),
    )


def parallel_retrieval_include_main(_: dict[str, Any], settings: Settings) -> bool:
    return bool(getattr(settings, "kb_chat_parallel_retrieval_include_main", True))
