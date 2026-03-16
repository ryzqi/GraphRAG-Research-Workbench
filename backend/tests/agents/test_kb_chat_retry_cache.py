from __future__ import annotations

from types import SimpleNamespace

from app.agents.answer_subgraph import build_answer_subgraph
from app.agents.evidence_gate_subgraph import build_evidence_gate_subgraph
from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph
from app.services.kb_chat_service import KbChatService


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "memory_enabled": False,
        "retrieval_default_top_k": 5,
        "retrieval_max_top_k": 50,
        "kb_chat_parallel_retrieval_min_queries": 2,
        "kb_chat_parallel_retrieval_max_branches": 6,
        "kb_chat_parallel_retrieval_include_main": True,
        "kb_chat_max_generation_retries": 2,
        "kb_chat_max_retrieval_retries": 2,
        "kb_chat_max_total_rounds": 3,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_kb_chat_graph_compile_omits_dead_graph_cache(monkeypatch) -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )
    captured: dict[str, object] = {}

    def _fake_compile(**kwargs: object) -> str:
        captured.update(kwargs)
        return "compiled"

    monkeypatch.setattr(graph._graph_builder, "compile", _fake_compile)

    result = graph.compile(checkpointer="ckpt", store="store")

    assert result == "compiled"
    assert captured["checkpointer"] == "ckpt"
    assert captured["store"] == "store"
    assert "cache" not in captured


def test_retry_policies_are_attached_only_to_transient_failure_nodes() -> None:
    preprocess = build_preprocess_subgraph(settings=_settings())
    retrieval = build_retrieval_subgraph(settings=_settings(), kb_tool=SimpleNamespace())
    evidence_gate = build_evidence_gate_subgraph(settings=_settings())
    answer = build_answer_subgraph(settings=_settings(), chat_model=SimpleNamespace())
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    assert preprocess.builder.nodes["complexity_classify"].retry_policy is not None
    assert retrieval.builder.nodes["retrieve_subquery"].retry_policy is not None
    assert retrieval.builder.nodes["retrieve"].retry_policy is not None
    assert graph._graph_builder.nodes["transform_query"].retry_policy is not None
    assert answer.builder.nodes["draft_generate"].retry_policy is not None
    assert answer.builder.nodes["answer_review_factual"].retry_policy is not None
    assert answer.builder.nodes["answer_review_answerability"].retry_policy is not None
    assert answer.builder.nodes["answer_repair"].retry_policy is not None

    assert evidence_gate.builder.nodes["doc_gate_sufficiency"].retry_policy is None
    assert evidence_gate.builder.nodes["doc_gate_answerability"].retry_policy is None
    assert evidence_gate.builder.nodes["doc_gate_conflict"].retry_policy is None


def test_non_retry_rule_nodes_publish_explicit_execution_metadata() -> None:
    evidence_gate = build_evidence_gate_subgraph(settings=_settings())
    sufficiency_meta = evidence_gate.builder.nodes["doc_gate_sufficiency"].metadata
    answerability_meta = evidence_gate.builder.nodes["doc_gate_answerability"].metadata

    assert sufficiency_meta["retry_enabled"] is False
    assert sufficiency_meta["side_effect_type"] == "deterministic_rule"
    assert sufficiency_meta["retry_disabled_reason"] == "deterministic_rule"

    assert answerability_meta["retry_enabled"] is False
    assert answerability_meta["side_effect_type"] == "deterministic_rule"


def test_retry_cache_metrics_publish_retry_breakdown_and_disabled_graph_cache() -> None:
    metrics = KbChatService._build_retry_cache_metrics(
        {
            "retrieve": 3,
            "answer_repair": 2,
            "legacy_alias": 1,
            "bad": -1,
        }
    )

    assert metrics == {
        "retry_attempts_total": 3,
        "retry_node_breakdown": {"retrieve": 2, "answer_repair": 1},
        "graph_cache_hit_total": 0,
        "graph_cache_miss_total": 0,
        "cache_disabled_reason": "compile_cache_disabled",
    }


def test_build_observability_includes_retry_cache_metrics() -> None:
    service = object.__new__(KbChatService)
    service._settings = _settings(kb_chat_trace_enabled=False)
    service._context_builder = SimpleNamespace(
        build_metrics=lambda **_: {"history_messages": 0}
    )
    service._retrieval = SimpleNamespace(last_stats={}, last_layer_draft=None)

    metrics, stage_summaries = service._build_observability(
        kb_chat_config=_settings(),
        history_usage={},
        history_truncation={},
        retrieval_meta={},
        retrieval_results=[],
        base_metrics={},
        base_stage_summaries={},
        stage_attempts={"retrieve": 3, "answer_repair": 2},
    )

    assert metrics["retry_attempts_total"] == 3
    assert metrics["retry_node_breakdown"] == {"retrieve": 2, "answer_repair": 1}
    assert metrics["graph_cache_hit_total"] == 0
    assert metrics["graph_cache_miss_total"] == 0
    assert metrics["cache_disabled_reason"] == "compile_cache_disabled"
    assert stage_summaries["retry_cache"]["retry_attempts_total"] == 3
    assert stage_summaries["retry_cache"]["retry_node_breakdown"] == {
        "retrieve": 2,
        "answer_repair": 1,
    }


def test_routing_contract_consistency_rejects_legacy_finalize_target() -> None:
    score = KbChatService._compute_route_consistency(
        query_strategy="direct",
        routing_decisions={
            "doc_gate": {"next_node": "answer_subgraph"},
            "answer_subgraph": {"next_node": "finalize"},
        },
    )

    assert score == round((2 / 3) * 100.0, 4)


def test_final_state_consistency_rejects_legacy_finalize_terminal() -> None:
    score = KbChatService._compute_final_state_consistency(
        routing_decisions={
            "answer_subgraph": {"next_node": "finalize"},
        },
        terminal_reason=None,
    )

    assert score == 0.0
