"""Helpers for KB chat runtime parameter resolution from graph state."""

from __future__ import annotations

from typing import Any
from langgraph.runtime import Runtime

from app.core.settings import Settings


def _runtime_context(runtime: Runtime[Any] | None) -> dict[str, Any]:
    if runtime is None:
        return {}
    context = getattr(runtime, "context", None)
    return context if isinstance(context, dict) else {}


def _runtime_config(runtime: Runtime[Any] | None) -> dict[str, Any]:
    context = _runtime_context(runtime)
    config = context.get("runtime_config")
    return config if isinstance(config, dict) else {}


def _state_int(
    state: dict[str, Any],
    *,
    key: str,
    default: int,
    runtime: Runtime[Any] | None = None,
) -> int:
    runtime_config = _runtime_config(runtime)
    if runtime_config:
        value = runtime_config.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    runtime_state = state.get("runtime_config")
    if isinstance(runtime_state, dict):
        value = runtime_state.get(key)
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
    runtime: Runtime[Any] | None = None,
) -> float:
    runtime_config = _runtime_config(runtime)
    if runtime_config:
        value = runtime_config.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    runtime_state = state.get("runtime_config")
    if isinstance(runtime_state, dict):
        value = runtime_state.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(default)


def normalize_alias_max(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> int:
    return max(
        1,
        min(
            8,
            _state_int(
                state,
                key="normalize_alias_max",
                default=int(getattr(settings, "kb_chat_normalize_alias_max", 4)),
                runtime=runtime,
            ),
        ),
    )


def entity_expand_max_candidates(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> int:
    return max(
        1,
        min(
            12,
            _state_int(
                state,
                key="entity_expand_max_candidates",
                default=int(getattr(settings, "kb_chat_entity_expand_max_candidates", 8)),
                runtime=runtime,
            ),
        ),
    )


def entity_expand_max_variants(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> int:
    max_candidates = entity_expand_max_candidates(state, settings, runtime=runtime)
    return max(
        1,
        min(
            max_candidates,
            _state_int(
                state,
                key="entity_expand_max_variants",
                default=int(getattr(settings, "kb_chat_entity_expand_max_variants", 6)),
                runtime=runtime,
            ),
        ),
    )


def entity_expand_min_confidence(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> float:
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
                runtime=runtime,
            ),
        ),
    )


def retrieval_top_k(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> int:
    retrieval_budget = state.get("retrieval_budget")
    if isinstance(retrieval_budget, dict):
        per_query_top_k = retrieval_budget.get("per_query_top_k")
        if isinstance(per_query_top_k, int) and per_query_top_k > 0:
            return per_query_top_k
    return max(
        1,
        _state_int(
            state,
            key="retrieval_top_k",
            default=int(settings.retrieval_default_top_k),
            runtime=runtime,
        ),
    )


def parallel_retrieval_min_queries(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> int:
    return max(
        1,
        min(
            8,
            _state_int(
                state,
                key="parallel_retrieval_min_queries",
                default=int(getattr(settings, "kb_chat_parallel_retrieval_min_queries", 2)),
                runtime=runtime,
            ),
        ),
    )


def parallel_retrieval_max_branches(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> int:
    return max(
        1,
        min(
            12,
            _state_int(
                state,
                key="parallel_retrieval_max_branches",
                default=int(getattr(settings, "kb_chat_parallel_retrieval_max_branches", 6)),
                runtime=runtime,
            ),
        ),
    )


def parallel_retrieval_include_main(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> bool:
    runtime_config = _runtime_config(runtime)
    include_main = runtime_config.get("parallel_retrieval_include_main")
    if isinstance(include_main, bool):
        return include_main
    runtime_state = state.get("runtime_config")
    if isinstance(runtime_state, dict) and isinstance(
        runtime_state.get("parallel_retrieval_include_main"), bool
    ):
        return bool(runtime_state.get("parallel_retrieval_include_main"))
    return bool(getattr(settings, "kb_chat_parallel_retrieval_include_main", True))
