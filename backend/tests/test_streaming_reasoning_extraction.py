from __future__ import annotations

from app.services.streaming import DeltaKind, extract_stream_delta


class _Token:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _kinds_and_content(deltas):
    return [(delta.kind, delta.content) for delta in deltas]


def test_extracts_anthropic_thinking_blocks_from_content_items() -> None:
    token = _Token(
        type="ai",
        content=[
            {"type": "thinking", "thinking": "thought-A"},
            {"type": "text", "text": "answer-A"},
        ],
    )

    deltas = extract_stream_delta(token, meta={"langgraph_node": "model"})

    assert _kinds_and_content(deltas) == [
        (DeltaKind.THINKING, "thought-A"),
        (DeltaKind.ANSWER, "answer-A"),
    ]


def test_extracts_openai_reasoning_summary_from_additional_kwargs() -> None:
    token = _Token(
        type="ai",
        content=[{"type": "text", "text": "answer-B"}],
        additional_kwargs={
            "reasoning": {
                "summary": [
                    {"type": "summary_text", "text": "summary-1"},
                    {"type": "summary_text", "text": "summary-2"},
                ]
            }
        },
    )

    deltas = extract_stream_delta(token, meta={"langgraph_node": "model"})

    assert _kinds_and_content(deltas) == [
        (DeltaKind.THINKING, "summary-1summary-2"),
        (DeltaKind.ANSWER, "answer-B"),
    ]


def test_extracts_reasoning_block_summary_field() -> None:
    token = _Token(
        type="ai",
        content=[
            {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "summary-3"},
                ],
            },
            {"type": "text", "text": "answer-C"},
        ],
    )

    deltas = extract_stream_delta(token, meta={"langgraph_node": "model"})

    assert _kinds_and_content(deltas) == [
        (DeltaKind.THINKING, "summary-3"),
        (DeltaKind.ANSWER, "answer-C"),
    ]
