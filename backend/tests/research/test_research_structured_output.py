from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from app.services.query_rewrite_service import coerce_structured_result_payload
from app.services.research_planner import _ResearchScoperOutput


def test_coerce_structured_result_payload_parses_invalid_tool_call_args_for_research_scoper() -> None:
    raw = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "id": "call_scoper",
                "name": "_ResearchScoperOutput",
                "args": json.dumps(
                    {
                        "decision": "clarify",
                        "summary": "需要先明确目标场景。",
                        "questions": [
                            {
                                "id": "scope",
                                "question": "你更关注个人使用还是团队落地？",
                                "why_it_matters": "目标不同会影响研究边界。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                "error": "tool schema validation failed",
            }
        ],
    )

    payload, reason = coerce_structured_result_payload(
        result={
            "raw": raw,
            "parsed": None,
            "parsing_error": ValueError("structured output parser rejected tool call"),
        },
        schema=_ResearchScoperOutput,
    )

    assert reason is None
    assert payload is not None
    assert payload.decision == "clarify"
    assert payload.questions[0].id == "scope"


def test_coerce_structured_result_payload_ignores_extra_top_level_fields_for_research_scoper() -> None:
    raw = AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "call_scoper",
                    "type": "function",
                    "function": {
                        "name": "_ResearchScoperOutput",
                        "arguments": json.dumps(
                            {
                                "decision": "clarify",
                                "summary": "需要先明确目标场景。",
                                "questions": [
                                    {
                                        "id": "scope",
                                        "question": "你更关注个人使用还是团队落地？",
                                        "why_it_matters": "目标不同会影响研究边界。",
                                    }
                                ],
                                "confidence": 0.82,
                            },
                            ensure_ascii=False,
                        ),
                    },
                }
            ]
        },
    )

    payload, reason = coerce_structured_result_payload(
        result={"raw": raw, "parsed": None, "parsing_error": None},
        schema=_ResearchScoperOutput,
    )

    assert reason is None
    assert payload is not None
    assert payload.decision == "clarify"
    assert payload.summary == "需要先明确目标场景。"