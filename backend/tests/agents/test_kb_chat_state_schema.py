from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.kb_chat_agentic_graph import (
    KbChatAgenticGraph,
    build_kb_chat_run_context,
)
from app.agents.kb_chat_contracts import STATE_SCHEMA_V3
from app.agents.kb_chat_agentic.preprocess import merge_context
from app.agents.kb_chat_agentic_state import (
    KbChatInternalState,
    KbChatInputState,
    KbChatOutputState,
    make_initial_state,
)
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph
from app.agents.evidence_gate_subgraph import build_evidence_gate_subgraph
from app.agents.retrieval_subgraph import _compress_context


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
    assert state["schema_version"] == STATE_SCHEMA_V3
    assert state["final_context"] == ""


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


def test_compress_context_writes_only_final_context() -> None:
    result = _compress_context(
        {
            "user_input": "当前问题",
            "final_context": "[S1] 证据内容",
            "stage_summaries": {},
        }
    )

    assert "compressed_context" not in result
    assert result["final_context"] == "[S1] 证据内容"
    assert result["stage_summaries"]["context_compress"]["output_tokens"] >= 1


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
    )
    evidence_gate = build_evidence_gate_subgraph(settings=settings)

    assert preprocess.builder.state_schema is KbChatInternalState
    assert retrieval.builder.state_schema is KbChatInternalState
    assert evidence_gate.builder.state_schema is KbChatInternalState
