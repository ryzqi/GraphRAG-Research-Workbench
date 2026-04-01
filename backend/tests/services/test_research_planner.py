from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from app.services.query_rewrite_service import coerce_structured_result_payload
from app.services.research_planner import _ResearchScoperOutput


def test_coerce_scoper_clarify_payload_accepts_null_proceed_only_fields() -> None:
    result = {
        "raw": SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "name": "_ResearchScoperOutput",
                    "args": {
                        "decision": "clarify",
                        "summary": "研究对象还不够具体，需要先补充关键范围。",
                        "questions": [
                            {
                                "id": "q1",
                                "question": "你要研究哪类 MCP？",
                                "why_it_matters": "不同对象会直接改变检索范围和输出结构。",
                            }
                        ],
                        "research_brief": None,
                        "complexity": None,
                        "target_sources": None,
                        "subtasks": None,
                        "budget_guidance": None,
                    },
                }
            ],
            invalid_tool_calls=[],
            additional_kwargs={},
        ),
        "parsed": None,
        "parsing_error": None,
    }

    payload, reason = coerce_structured_result_payload(
        result=result,
        schema=_ResearchScoperOutput,
    )

    assert reason is None
    assert payload is not None
    assert payload.decision == "clarify"
    assert payload.questions[0].id == "q1"
    assert payload.target_sources == []
    assert payload.subtasks == []


def test_coerce_scoper_proceed_payload_accepts_object_research_brief() -> None:
    result = {
        "raw": SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "name": "_ResearchScoperOutput",
                    "args": {
                        "decision": "proceed",
                        "summary": "信息已足够，直接进入研究。",
                        "questions": None,
                        "research_brief": {
                            "objectives": ["比较两条路线"],
                            "scope": {"audience": "20 人研发团队"},
                        },
                        "complexity": "comparative",
                        "target_sources": ["web", "paper"],
                        "subtasks": [
                            {
                                "title": "事实收集",
                                "description": "汇总官方资料与公开评测。",
                                "target_sources": ["web"],
                            }
                        ],
                        "budget_guidance": "优先官方资料。",
                    },
                }
            ],
            invalid_tool_calls=[],
            additional_kwargs={},
        ),
        "parsed": None,
        "parsing_error": None,
    }

    payload, reason = coerce_structured_result_payload(
        result=result,
        schema=_ResearchScoperOutput,
    )

    assert reason is None
    assert payload is not None
    assert payload.decision == "proceed"
    assert isinstance(payload.research_brief, str)
    assert "objectives" in payload.research_brief
