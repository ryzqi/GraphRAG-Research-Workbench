from __future__ import annotations

from types import SimpleNamespace

from app.agents.kb_chat_trace_nodes import KB_CHAT_NODE_METADATA
from app.agents.preprocess_subgraph import build_preprocess_subgraph


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "kb_chat_parallel_retrieval_min_queries": 2,
        "kb_chat_parallel_retrieval_max_branches": 6,
        "kb_chat_parallel_retrieval_include_main": True,
        "kb_chat_max_generation_retries": 2,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_query_plan_restores_scheme_b_enhancement_nodes_in_live_catalog() -> None:
    assert "query_plan" in KB_CHAT_NODE_METADATA
    assert "query_plan_finalize" in KB_CHAT_NODE_METADATA
    assert "decomposition" in KB_CHAT_NODE_METADATA
    assert "generate_variants" in KB_CHAT_NODE_METADATA
    assert "entity_expand" in KB_CHAT_NODE_METADATA
    assert "hyde" in KB_CHAT_NODE_METADATA
    assert "prepare_messages" not in KB_CHAT_NODE_METADATA
    assert "complexity_classify" not in KB_CHAT_NODE_METADATA
    assert "generate_variants_mod" not in KB_CHAT_NODE_METADATA


def test_preprocess_subgraph_restores_scheme_b_post_normalize_chain() -> None:
    preprocess = build_preprocess_subgraph(settings=_settings())
    node_ids = set(preprocess.builder.nodes.keys())

    assert {
        "query_plan",
        "decomposition",
        "generate_variants",
        "entity_expand",
        "hyde",
        "query_plan_finalize",
    }.issubset(node_ids)
    assert {
        "complexity_classify",
        "generate_variants_mod",
        "prepare_messages",
    }.isdisjoint(node_ids)
