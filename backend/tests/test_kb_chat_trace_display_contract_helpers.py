from __future__ import annotations

from app.agents import kb_chat_trace_display_contract
from app.agents.kb_chat_trace_display_input import build_node_input_display_items
from app.agents.kb_chat_trace_display_output import build_node_output_display_items


def _resolve_node_label(node_name: str | None) -> str | None:
    if node_name == "decomposition":
        return "问题拆解"
    return None


def test_kb_chat_trace_display_helpers_and_reexports() -> None:
    input_items = build_node_input_display_items(
        node_name="query_plan_finalize",
        snapshot={
            "normalized_query": "比较 A 和 B",
            "sub_queries": ["A 的优势", "B 的优势"],
            "multi_queries": ["A vs B"],
        },
        node_label_resolver=_resolve_node_label,
    )
    output_items = build_node_output_display_items(
        node_name="query_plan",
        snapshot={
            "query_strategy": "decomposition",
            "__trace_command__": {"goto": "decomposition"},
            "stage_summaries": {
                "query_plan": {"strategy": "decomposition", "is_comparison": True}
            },
        },
        node_label_resolver=_resolve_node_label,
    )

    assert [item["key"] for item in input_items] == [
        "normalized_query",
        "sub_queries",
        "multi_queries",
    ]
    assert input_items[0]["value"] == "比较 A 和 B"
    assert output_items[0] == {"key": "decision", "label": "结论", "value": "复杂问题"}
    assert output_items[1]["value"] == "命中比较或多目标信号，先做问题拆解，再进入 HyDE 补强。"
    assert output_items[2] == {
        "key": "next_node_label",
        "label": "下一跳",
        "value": "问题拆解",
    }
    assert (
        kb_chat_trace_display_contract.build_node_input_display_items
        is build_node_input_display_items
    )
    assert (
        kb_chat_trace_display_contract.build_node_output_display_items
        is build_node_output_display_items
    )
