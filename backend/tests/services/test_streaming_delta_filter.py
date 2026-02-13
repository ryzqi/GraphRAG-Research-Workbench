from __future__ import annotations

from types import SimpleNamespace

from app.services.streaming import DeltaKind, extract_stream_delta


def test_extract_stream_delta_drops_answer_tokens_from_non_generation_nodes() -> None:
    token = SimpleNamespace(content='{"passed": true}')

    deltas = extract_stream_delta(
        token=token,
        meta={"langgraph_node": "doc_grader"},
    )

    assert all(delta.kind != DeltaKind.ANSWER for delta in deltas)


def test_extract_stream_delta_keeps_answer_tokens_for_generate_node() -> None:
    token = SimpleNamespace(content="这是回答内容。")

    deltas = extract_stream_delta(
        token=token,
        meta={"langgraph_node": "generate"},
    )

    assert any(delta.kind == DeltaKind.ANSWER for delta in deltas)
