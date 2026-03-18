from __future__ import annotations

from typing import get_type_hints
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain.messages import AIMessage, HumanMessage

from app.agents.answer_subgraph import build_answer_subgraph
from app.agents.evidence_gate_subgraph import _doc_gate_route, _doc_gate_sufficiency
from app.agents.kb_chat_agentic.answer_subgraph import (
    _answer_commit,
    _answer_repair,
    _answer_review_answerability,
    _answer_review_citation,
    _answer_review_dispatch,
    _answer_review_factual,
    _answer_review_fuse,
)
from app.agents.kb_chat_agentic.reflection import (
    confidence_calibrate,
    dispatch_subqueries,
    kb_retrieve_context,
    merge_subquery_context,
    retrieve_subquery_context,
    route_after_answer_review,
    route_after_doc_grader,
    transform_query_for_retry,
)
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic_graph import (
    KbChatAgenticGraph,
    _route_after_preprocess_subgraph,
    build_kb_chat_run_context,
)
from app.agents.kb_chat_contracts import STATE_SCHEMA_V3
from app.agents.kb_chat_trace_nodes import KB_CHAT_NODE_METADATA
from app.agents.kb_chat_agentic.preprocess import (
    ambiguity_check,
    complexity_classify,
    coref_rewrite,
    merge_context,
    normalize_rewrite,
    prepare_messages,
)
from app.agents.kb_chat_agentic_state import (
    build_graph_input_state,
    KbChatInternalState,
    KbChatInputState,
    KbChatOutputState,
    make_initial_state,
)
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph
from app.agents.evidence_gate_subgraph import build_evidence_gate_subgraph
from app.agents.retrieval_subgraph import _compress_context, _retrieval_budget_plan


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "memory_enabled": False,
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_make_initial_state_omits_legacy_duplicate_context_fields() -> None:
    state = make_initial_state(user_input="当前问题")

    assert "display_context" not in state
    assert "compressed_context" not in state
    assert "memory_keys" not in state
    assert "runtime_config" not in state
    assert "preprocess_next" not in state
    assert "doc_gate_state" not in state
    assert "doc_gate_scores" not in state
    assert "answer_quality" not in state
    assert "sub_queries" not in state
    assert "multi_queries" not in state
    assert "hyde_docs" not in state
    assert "message_plan" not in state
    assert "query_bundle" not in state
    assert "prepare_diagnostics" not in state
    assert "query_items" not in state
    assert "subquery_runs" not in state
    assert "retrieval_budget" not in state
    assert "retrieval_diagnostics" not in state
    assert "final_context" not in state
    assert "compression_stats" not in state
    assert "answer_subgraph_state" not in state
    assert "doc_gate_round" not in state
    assert "doc_gate_runs" not in state
    assert "cove_state" not in state
    assert "routing_decisions" not in state
    assert "decomposition_plan" not in state
    assert "answer_review_runs" not in state
    assert state["schema_version"] == STATE_SCHEMA_V3
    assert set(state) == {
        "messages",
        "user_input",
        "schema_version",
        "pending_tool_calls",
        "loop_counts",
        "stage_summaries",
        "metrics",
    }


def test_internal_state_schema_omits_removed_cove_state_field() -> None:
    assert "cove_state" not in get_type_hints(KbChatInternalState)


def _state_annotation_name(fn: object) -> str:
    annotation = get_type_hints(fn).get("state")
    return getattr(annotation, "__name__", str(annotation))


def test_kb_chat_nodes_use_narrow_read_side_state_schema_annotations() -> None:
    expected = {
        merge_context: "MergeContextInput",
        coref_rewrite: "CorefRewriteInput",
        ambiguity_check: "AmbiguityCheckInput",
        normalize_rewrite: "NormalizeRewriteInput",
        complexity_classify: "ComplexityClassifyInput",
        prepare_messages: "PrepareMessagesInput",
        _retrieval_budget_plan: "RetrievalBudgetPlanInput",
        dispatch_subqueries: "DispatchSubqueriesInput",
        retrieve_subquery_context: "RetrieveSubqueryContextInput",
        merge_subquery_context: "MergeSubqueryContextInput",
        kb_retrieve_context: "RetrieveContextInput",
        _compress_context: "CompressContextInput",
        _doc_gate_sufficiency: "DocGateContextInput",
        _doc_gate_route: "DocGateRouteInput",
        transform_query_for_retry: "TransformQueryInput",
        _answer_review_dispatch: "AnswerReviewDispatchInput",
        _answer_review_citation: "AnswerReviewCitationInput",
        _answer_review_factual: "AnswerReviewLLMInput",
        _answer_review_answerability: "AnswerReviewLLMInput",
        _answer_review_fuse: "AnswerReviewFuseInput",
        _answer_repair: "AnswerRepairInput",
        _answer_commit: "AnswerCommitInput",
        force_exit_node: "ForceExitInput",
        confidence_calibrate: "ConfidenceCalibrateInput",
        _route_after_preprocess_subgraph: "PreprocessRoutingInput",
        route_after_doc_grader: "DocGateRoutingDecisionInput",
        route_after_answer_review: "AnswerRoutingDecisionInput",
    }

    actual = {fn.__name__: _state_annotation_name(fn) for fn in expected}

    assert actual == {fn.__name__: name for fn, name in expected.items()}


def test_preprocess_subgraph_prunes_route_shell_nodes_from_builder() -> None:
    settings = _settings(
        retrieval_default_top_k=5,
        retrieval_max_top_k=50,
        kb_chat_parallel_retrieval_min_queries=2,
        kb_chat_parallel_retrieval_max_branches=6,
        kb_chat_parallel_retrieval_include_main=True,
        kb_chat_max_total_rounds=3,
        kb_chat_max_generation_retries=2,
        kb_chat_ambiguity_check_enabled=True,
        kb_chat_multi_query_mod_enabled=True,
        kb_chat_decomposition_enabled=True,
        kb_chat_multi_query_enabled=True,
        kb_chat_hyde_enabled=True,
    )

    preprocess = build_preprocess_subgraph(settings=settings)
    node_ids = set(preprocess.builder.nodes.keys())
    branch_ids = set(preprocess.builder.branches.keys())
    removed_nodes = {
        "AMBIGUITY_CHECK_ENABLED",
        "adaptive_routing",
        "simple_path",
        "moderate_path",
        "complex_path",
        "ENABLE_MULTI_QUERY_MOD",
        "ENABLE_DECOMPOSITION",
        "ENABLE_MULTI_QUERY",
        "ENABLE_HYDE",
    }

    assert removed_nodes.isdisjoint(node_ids)
    assert removed_nodes.isdisjoint(branch_ids)


def test_trace_metadata_prunes_preprocess_shell_nodes() -> None:
    removed_nodes = {
        "AMBIGUITY_CHECK_ENABLED",
        "adaptive_routing",
        "simple_path",
        "moderate_path",
        "complex_path",
        "ENABLE_MULTI_QUERY_MOD",
        "ENABLE_DECOMPOSITION",
        "ENABLE_MULTI_QUERY",
        "ENABLE_HYDE",
    }

    assert removed_nodes.isdisjoint(KB_CHAT_NODE_METADATA)


def test_build_graph_input_state_strips_internal_fields() -> None:
    public_input = build_graph_input_state(
        {
            "messages": [],
            "user_input": "当前问题",
            "stage_summaries": {"checkpoint_restore": {"applied": True}},
            "metrics": {"context": {"history_turns": 2}},
            "loop_counts": {
                "total_rounds": 3,
                "retrieval_retries": 1,
                "generation_retries": 0,
            },
            "final_answer": "不应透传",
        }
    )

    assert public_input == {
        "messages": [],
        "user_input": "当前问题",
    }


@pytest.mark.asyncio
async def test_merge_context_writes_only_merged_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess._generate_summary_from_turns",
        AsyncMock(return_value=""),
    )

    result = await merge_context(
        {
            "messages": [],
            "user_input": "当前问题",
            "metrics": {},
            "stage_summaries": {},
        },
        runtime=SimpleNamespace(store=None),
        settings=_settings(),
    )

    assert "display_context" not in result
    assert result["merged_context"] == "用户问题：当前问题"


@pytest.mark.asyncio
async def test_merge_context_dedupes_duplicate_recent_assistant_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess._generate_summary_from_turns",
        AsyncMock(return_value=""),
    )
    answer = "CoT 是把复杂任务拆成逐步推理链条的方法。"

    result = await merge_context(
        {
            "messages": [
                HumanMessage(content="什么是CoT"),
                AIMessage(content=answer),
                HumanMessage(content="什么是CoT"),
                AIMessage(content=answer),
            ],
            "user_input": "什么是CoT",
            "metrics": {},
            "stage_summaries": {},
        },
        runtime=SimpleNamespace(store=None),
        settings=_settings(),
    )

    assert result["context_frame"]["selected_turns"] == [
        {"role": "assistant", "text": answer}
    ]
    assert result["merged_context"] == f"最近对话：\n助手: {answer}\n\n用户问题：什么是CoT"


@pytest.mark.asyncio
async def test_merge_context_omits_memory_already_covered_by_recent_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess._generate_summary_from_turns",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.aget_kb_chat_memory",
        AsyncMock(
            return_value={
                "entries": [
                    {
                        "q": "什么是CoT",
                        "a": "CoT 是把复杂任务拆成逐步推理链条的方法。",
                    }
                ]
            }
        ),
    )
    answer = "CoT 是把复杂任务拆成逐步推理链条的方法。"

    result = await merge_context(
        {
            "messages": [
                HumanMessage(content="什么是CoT"),
                AIMessage(content=answer),
            ],
            "user_input": "什么是CoT",
            "metrics": {},
            "stage_summaries": {},
        },
        runtime=SimpleNamespace(
            store=object(),
            context={"thread_id": "thread-1", "user_id": "user-1", "kb_ids": ["kb-1"]},
        ),
        settings=_settings(memory_enabled=True),
    )

    assert result["context_frame"]["memory_snippet"] == ""
    assert "会话记忆（近期）" not in result["merged_context"]
    assert result["merged_context"] == f"最近对话：\n助手: {answer}\n\n用户问题：什么是CoT"


@pytest.mark.asyncio
async def test_compress_context_fail_open_keeps_raw_context_when_llm_returns_empty() -> None:
    class _FakeChatModel:
        def bind(self, **_: object) -> "_FakeChatModel":
            return self

        async def ainvoke(self, _messages: object) -> SimpleNamespace:
            return SimpleNamespace(content="")

    result = await _compress_context(
        {
            "user_input": "当前问题",
            "normalized_query": "当前问题",
            "final_context": "[S1] 证据内容",
            "stage_summaries": {},
        },
        runtime=SimpleNamespace(context={}),
        settings=_settings(),
        chat_model=_FakeChatModel(),
    )

    assert "compressed_context" not in result
    assert result["final_context"] == "[S1] 证据内容"
    assert result["compression_stats"]["fallback_reason"] == "empty_compress_output"
    assert result["stage_summaries"]["context_compress"]["decision_source"] == "llm"


def test_build_kb_chat_run_context_prefers_authoritative_inputs() -> None:
    context = build_kb_chat_run_context(
        thread_id="thread-live",
        state={
            "memory_keys": {
                "user_id": "stale-user",
                "thread_id": "stale-thread",
                "kb_ids": ["stale-kb"],
            },
            "runtime_config": {"parallel_retrieval_max_branches": 99},
        },
        user_id="live-user",
        kb_ids=["kb-1", "kb-2"],
        runtime_config={"parallel_retrieval_max_branches": 3},
        settings=_settings(kb_chat_parallel_retrieval_max_branches=6),
    )

    assert context["thread_id"] == "thread-live"
    assert context["user_id"] == "live-user"
    assert context["kb_ids"] == ["kb-1", "kb-2"]
    assert context["runtime_config"]["parallel_retrieval_max_branches"] == 3
    assert context["message_budget"]["max_candidates"] == 3


def test_kb_chat_graph_uses_public_input_output_schema() -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    assert graph._graph_builder.state_schema is KbChatInternalState
    assert graph._graph_builder.input_schema is KbChatInputState
    assert graph._graph_builder.output_schema is KbChatOutputState


@pytest.mark.asyncio
async def test_kb_chat_graph_run_projects_public_input_before_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )
    captured: dict[str, object] = {}

    class _FakeCompiled:
        async def ainvoke(self, state, config, context=None):
            captured["state"] = state
            captured["config"] = config
            captured["context"] = context
            return {"final_answer": "ok"}

    monkeypatch.setattr(graph, "compile", lambda **kwargs: _FakeCompiled())

    await graph.run(
        {
            "messages": [],
            "user_input": "当前问题",
            "stage_summaries": {"checkpoint_restore": {"applied": True}},
            "metrics": {"context": {"history_turns": 2}},
            "loop_counts": {
                "total_rounds": 3,
                "retrieval_retries": 1,
                "generation_retries": 0,
            },
        },
        thread_id="thread-1",
    )

    assert captured["state"] == {
        "messages": [],
        "user_input": "当前问题",
    }


def test_kb_chat_subgraphs_share_internal_state_schema() -> None:
    settings = _settings(
        retrieval_default_top_k=5,
        retrieval_max_top_k=50,
        kb_chat_parallel_retrieval_min_queries=2,
        kb_chat_parallel_retrieval_max_branches=6,
        kb_chat_parallel_retrieval_include_main=True,
        kb_chat_max_total_rounds=3,
        kb_chat_max_generation_retries=2,
    )

    preprocess = build_preprocess_subgraph(settings=settings)
    retrieval = build_retrieval_subgraph(
        settings=settings,
        kb_tool=SimpleNamespace(),
        chat_model=SimpleNamespace(),
    )
    evidence_gate = build_evidence_gate_subgraph(settings=settings)

    assert preprocess.builder.state_schema is KbChatInternalState
    assert retrieval.builder.state_schema is KbChatInternalState
    assert evidence_gate.builder.state_schema is KbChatInternalState


def test_pruned_nodes_absent_from_live_subgraphs() -> None:
    settings = _settings(
        retrieval_default_top_k=5,
        retrieval_max_top_k=50,
        kb_chat_parallel_retrieval_min_queries=2,
        kb_chat_parallel_retrieval_max_branches=6,
        kb_chat_parallel_retrieval_include_main=True,
        kb_chat_max_total_rounds=3,
        kb_chat_max_generation_retries=2,
        kb_chat_max_retrieval_retries=2,
    )
    retrieval = build_retrieval_subgraph(
        settings=settings,
        kb_tool=SimpleNamespace(),
        chat_model=SimpleNamespace(),
    )
    evidence_gate = build_evidence_gate_subgraph(settings=settings)
    answer = build_answer_subgraph(settings=settings, chat_model=SimpleNamespace())

    assert {
        "doc_gate_dispatch",
        "doc_gate_answerability",
        "doc_gate_conflict",
        "doc_gate_fuse",
    }.isdisjoint(evidence_gate.builder.nodes)
    assert {
        "cove_check",
        "chain_of_verification",
        "claim_citation_check",
    }.isdisjoint(answer.builder.nodes)
    assert "context_compress" in retrieval.builder.nodes
