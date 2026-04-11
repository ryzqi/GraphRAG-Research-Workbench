from __future__ import annotations

from app.agents.kb_chat_agentic.schemas import NormalizeDecision
from app.services import query_rewrite_service
from app.services.query_rewrite_contracts import HYDE_AGGREGATION
from app.services.query_rewrite_items import build_query_items
from app.services.query_rewrite_structured import coerce_structured_result_payload
from app.services.query_rewrite_text import _looks_stable_overview_query


def test_query_rewrite_helper_modules_preserve_public_contract() -> None:
    items = build_query_items(
        main_query="RAG 的核心组件有哪些？",
        sub_queries=["RAG 的检索层", "RAG 的生成层"],
        variants=["RAG 核心组件 列表"],
        hyde_docs=["假设文档 A", "假设文档 A", "假设文档 B"],
        hyde_note="dense only",
    )

    assert [item["kind"] for item in items] == ["main", "subquery", "subquery", "variant", "hyde"]
    assert items[-1]["hyde_aggregation"] == HYDE_AGGREGATION
    assert items[-1]["hyde_queries"] == ["假设文档 A", "假设文档 B"]
    assert _looks_stable_overview_query("RAG 的核心组件有哪些？") is True


def test_query_rewrite_structured_parser_and_service_reexports() -> None:
    payload, reason = coerce_structured_result_payload(
        result='{"canonical_query":"RAG 技术架构","constraint_preserved":true,"drift_risk":false,"aliases":[],"entities":[],"time_constraints":[],"metric_constraints":[],"scope_constraints":[],"recall_risk":"low","has_multi_target":false,"is_comparison":false,"reasoning":"ok"}',
        schema=NormalizeDecision,
    )

    assert reason is None
    assert payload is not None
    assert payload.canonical_query == "RAG 技术架构"
    assert query_rewrite_service.build_query_items is build_query_items
    assert query_rewrite_service.coerce_structured_result_payload is coerce_structured_result_payload
    assert query_rewrite_service._looks_stable_overview_query is _looks_stable_overview_query