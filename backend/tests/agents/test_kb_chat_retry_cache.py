from __future__ import annotations

from types import SimpleNamespace

from app.agents.answer_subgraph import build_answer_subgraph
from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph
from app.services.kb_chat_service import KbChatService
from app.services.kb_chat_service import _KB_CHAT_CHECKPOINT_RESET_FIELDS


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
    retrieval = build_retrieval_subgraph(
        settings=_settings(), kb_tool=SimpleNamespace(), chat_model=SimpleNamespace()
    )
    answer = build_answer_subgraph(settings=_settings(), chat_model=SimpleNamespace())
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    assert preprocess.builder.nodes["query_normalize"].retry_policy is not None
    assert preprocess.builder.nodes["query_plan"].retry_policy is None
    assert retrieval.builder.nodes["retrieve_subquery"].retry_policy is not None
    assert retrieval.builder.nodes["retrieve"].retry_policy is not None
    assert graph._graph_builder.nodes["transform_query"].retry_policy is not None
    assert answer.builder.nodes["draft_generate"].retry_policy is not None
    assert answer.builder.nodes["answer_review"].retry_policy is not None
    assert answer.builder.nodes["answer_repair"].retry_policy is not None

    assert "retrieval_plan" in retrieval.builder.nodes
    assert "retrieval_budget_plan" not in retrieval.builder.nodes
    assert "evidence_gate_subgraph" not in graph._graph_builder.nodes
    assert "confidence_calibrate" not in graph._graph_builder.nodes
    assert {
        "cove_check",
        "chain_of_verification",
        "claim_citation_check",
    }.isdisjoint(answer.builder.nodes)


def test_retrieval_plan_publishes_llm_execution_metadata_without_retry_policy() -> None:
    retrieval = build_retrieval_subgraph(
        settings=_settings(), kb_tool=SimpleNamespace(), chat_model=SimpleNamespace()
    )
    planner_meta = retrieval.builder.nodes["retrieval_plan"].metadata

    assert planner_meta["retry_enabled"] is False
    assert planner_meta["side_effect_type"] == "llm"
    assert planner_meta["retry_disabled_reason"] == "llm"


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


def test_routing_contract_consistency_accepts_terminal_end_target() -> None:
    score = KbChatService._compute_route_consistency(
        query_strategy="direct",
        routing_decisions={
            "answer_subgraph": {"next_node": "END"},
        },
    )

    assert score == 100.0


def test_final_state_consistency_accepts_terminal_end_target() -> None:
    score = KbChatService._compute_final_state_consistency(
        routing_decisions={
            "answer_subgraph": {"next_node": "END"},
        },
        terminal_reason=None,
    )

    assert score == 100.0


def test_checkpoint_reset_fields_drop_removed_gate_and_confidence_state() -> None:
    assert "cove_state" not in _KB_CHAT_CHECKPOINT_RESET_FIELDS
    assert "doc_gate_round" not in _KB_CHAT_CHECKPOINT_RESET_FIELDS
    assert "doc_gate_runs" not in _KB_CHAT_CHECKPOINT_RESET_FIELDS
    assert "confidence_score" not in _KB_CHAT_CHECKPOINT_RESET_FIELDS
    assert "confidence_level" not in _KB_CHAT_CHECKPOINT_RESET_FIELDS
