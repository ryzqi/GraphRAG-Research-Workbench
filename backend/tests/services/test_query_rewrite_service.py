from __future__ import annotations

from app.services.query_rewrite_service import (
    _entity_seed_queries,
    _rule_normalize_query,
    build_query_items,
)


def test_build_query_items_drops_invisible_only_candidates() -> None:
    items = build_query_items(
        main_query="main query",
        sub_queries=["\u200e", "sub query"],
        variants=["\u2066", "variant query"],
        hyde_docs=["\u00ad", "hyde query"],
    )

    assert items == [
        {
            "kind": "main",
            "query": "main query",
            "use_dense": True,
            "use_bm25": True,
        },
        {
            "kind": "subquery",
            "query": "sub query",
            "index": 1,
            "origin": "decomposition",
            "subquery_id": "sq_2",
            "priority": 2,
            "coverage_tags": [],
            "purpose": "",
            "use_dense": True,
            "use_bm25": True,
        },
        {
            "kind": "variant",
            "query": "variant query",
            "index": 1,
            "use_dense": True,
            "use_bm25": True,
        },
        {
            "kind": "hyde",
            "query": "hyde query",
            "index": 0,
            "use_dense": True,
            "use_bm25": False,
            "hyde_queries": ["hyde query"],
            "hyde_aggregation": "mean_embedding",
        },
    ]


def test_rule_normalize_query_does_not_promote_focus_terms_to_aliases() -> None:
    query, meta = _rule_normalize_query("介绍一下react框架", alias_limit=4)

    assert query == "介绍一下react框架"
    assert meta["entities"] == ["react", "介绍一下", "框架"]
    assert meta["aliases"] == []


def test_entity_seed_queries_do_not_append_aliases_or_entities() -> None:
    seed = _entity_seed_queries(
        normalized_query="介绍一下react框架",
        queries=["react 框架"],
        aliases=["react"],
        entities=["react", "框架"],
        max_candidates=8,
    )

    assert seed == ["介绍一下react框架", "react 框架"]
