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


def normalize_llm_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="normalize_llm_enabled",
        default=bool(getattr(settings, "kb_chat_normalize_llm_enabled", True)),
    )


def normalize_alias_max(state: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(
            8,
            _state_int(
                state,
                key="normalize_alias_max",
                default=int(getattr(settings, "kb_chat_normalize_alias_max", 4)),
            ),
        ),
    )


def normalize_timeout_seconds(state: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        _state_float(
            state,
            key="normalize_timeout_seconds",
            default=float(getattr(settings, "kb_chat_normalize_timeout_seconds", 0.8)),
        ),
    )


def hyde_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="hyde_enabled",
        default=bool(settings.kb_chat_hyde_enabled),
    )


def entity_expand_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="entity_expand_enabled",
        default=bool(getattr(settings, "kb_chat_entity_expand_enabled", True)),
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


def parallel_retrieval_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="parallel_retrieval_enabled",
        default=bool(getattr(settings, "kb_chat_parallel_retrieval_enabled", True)),
    )


def parallel_retrieval_min_queries(state: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(
            8,
            _state_int(
                state,
                key="parallel_retrieval_min_queries",
                default=int(
                    getattr(settings, "kb_chat_parallel_retrieval_min_queries", 2)
                ),
            ),
        ),
    )


def parallel_retrieval_max_branches(state: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(
            12,
            _state_int(
                state,
                key="parallel_retrieval_max_branches",
                default=int(
                    getattr(settings, "kb_chat_parallel_retrieval_max_branches", 6)
                ),
            ),
        ),
    )


def parallel_retrieval_include_main(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="parallel_retrieval_include_main",
        default=bool(
            getattr(settings, "kb_chat_parallel_retrieval_include_main", True)
        ),
    )


def rewrite_branch_enabled(state: dict[str, Any], settings: Settings) -> bool:
    return _state_flag(
        state,
        key="rewrite_branch_enabled",
        default=bool(getattr(settings, "kb_chat_rewrite_branch_enabled", True)),
    )


def rewrite_branch_max_candidates(state: dict[str, Any], settings: Settings) -> int:
    return max(
        1,
        min(
            8,
            _state_int(
                state,
                key="rewrite_branch_max_candidates",
                default=int(
                    getattr(settings, "kb_chat_rewrite_branch_max_candidates", 4)
                ),
            ),
        ),
    )


def rewrite_min_confidence(state: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        min(
            1.0,
            _state_float(
                state,
                key="rewrite_min_confidence",
                default=float(getattr(settings, "kb_chat_rewrite_min_confidence", 0.55)),
            ),
        ),
    )


def doc_gate_rule_threshold(state: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        min(
            1.0,
            _state_float(
                state,
                key="doc_gate_rule_threshold",
                default=float(
                    getattr(settings, "kb_chat_doc_gate_rule_threshold", 0.45)
                ),
            ),
        ),
    )


def doc_gate_llm_confidence_floor(state: dict[str, Any], settings: Settings) -> float:
    return max(
        0.0,
        min(
            1.0,
            _state_float(
                state,
                key="doc_gate_llm_confidence_floor",
                default=float(
                    getattr(settings, "kb_chat_doc_gate_llm_confidence_floor", 0.45)
                ),
            ),
        ),
    )


def doc_gate_fallback_open_when_evidence_ok(
    state: dict[str, Any], settings: Settings
) -> bool:
    return _state_flag(
        state,
        key="doc_gate_fallback_open_when_evidence_ok",
        default=bool(
            getattr(settings, "kb_chat_doc_gate_fallback_open_when_evidence_ok", True)
        ),
    )


def doc_gate_cache_ttl_seconds(state: dict[str, Any], settings: Settings) -> int:
    return max(
        0,
        _state_int(
            state,
            key="doc_gate_cache_ttl_seconds",
            default=int(getattr(settings, "kb_chat_doc_gate_cache_ttl_seconds", 60)),
        ),
    )
