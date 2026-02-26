from __future__ import annotations

import types
from typing import Any

from langchain.tools import BaseTool

from app.agents.answer_subgraph import build_answer_subgraph
from app.agents.evidence_gate_subgraph import build_evidence_gate_subgraph
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph


class _DummyChatModel:
    pass


class _DummyRetrieveTool(BaseTool):
    name: str = "kb_retrieve"
    description: str = "dummy kb tool for graph compile tests"

    def _run(self, *args: Any, **kwargs: Any) -> str:
        return ""

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return ""


def _default_settings() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        kb_chat_max_generation_retries=1,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
        kb_chat_grader_fail_policy="closed",
        kb_chat_doc_gate_rule_threshold=0.35,
        kb_chat_doc_gate_llm_confidence_floor=0.55,
        kb_chat_doc_gate_fallback_open_when_evidence_ok=True,
    )


def test_preprocess_subgraph_entrypoint_compiles() -> None:
    compiled = build_preprocess_subgraph(settings=_default_settings())
    graph_json = compiled.get_graph().to_json()
    assert graph_json.get("nodes")
    node_ids = {node.get("id") for node in graph_json.get("nodes") if isinstance(node, dict)}
    assert "merge_context" in node_ids


def test_retrieval_subgraph_entrypoint_compiles() -> None:
    compiled = build_retrieval_subgraph(
        settings=_default_settings(),
        kb_tool=_DummyRetrieveTool(),
    )
    graph_json = compiled.get_graph().to_json()
    assert graph_json.get("nodes")
    node_ids = {node.get("id") for node in graph_json.get("nodes") if isinstance(node, dict)}
    assert "retrieve" in node_ids


def test_evidence_gate_subgraph_entrypoint_compiles() -> None:
    compiled = build_evidence_gate_subgraph(settings=_default_settings())
    graph_json = compiled.get_graph().to_json()
    assert graph_json.get("nodes")
    node_ids = {node.get("id") for node in graph_json.get("nodes") if isinstance(node, dict)}
    assert "doc_gate_precheck" in node_ids


def test_answer_subgraph_entrypoint_compiles() -> None:
    compiled = build_answer_subgraph(
        settings=_default_settings(),
        chat_model=_DummyChatModel(),
    )
    assert compiled.get_graph().to_json().get("nodes")
