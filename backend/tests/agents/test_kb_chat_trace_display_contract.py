from __future__ import annotations

from app.agents.kb_chat_trace_display_contract import build_node_output_display_items


def _item_by_key(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        str(item["key"]): item
        for item in items
    }


def test_merge_context_displays_merged_context_even_without_summary_or_memory() -> None:
    items = build_node_output_display_items(
        node_name="merge_context",
        snapshot={
            "merged_context": "当前问题：\nCoT 和 ToT 有什么区别？",
            "context_frame": {
                "summary_text": "",
                "memory_snippet": "",
                "recent_turns": [],
                "selected_turns": [],
                "current_question": "CoT 和 ToT 有什么区别？",
            },
        },
    )

    assert _item_by_key(items)["merged_context"]["value"] == "当前问题：\nCoT 和 ToT 有什么区别？"


def test_hyde_displays_generated_documents_when_available() -> None:
    items = build_node_output_display_items(
        node_name="hyde",
        snapshot={
            "hyde_docs": ["第一段假设文档", "第二段假设文档"],
            "stage_summaries": {
                "hyde": {
                    "success": True,
                    "generated_count": 2,
                    "reason": "llm_structured",
                }
            },
        },
    )

    assert _item_by_key(items)["hyde_docs"]["value"] == ["第一段假设文档", "第二段假设文档"]


def test_hyde_displays_fallback_message_when_no_document_is_generated() -> None:
    items = build_node_output_display_items(
        node_name="hyde",
        snapshot={
            "normalized_query": "CoT 和 ToT 的区别",
            "stage_summaries": {
                "hyde": {
                    "success": False,
                    "generated_count": 0,
                    "reason": "llm_failed_fallback_empty",
                }
            },
        },
    )

    assert _item_by_key(items)["hyde_docs"]["value"] == ["本轮未生成 HyDE 文档，已沿原问题继续检索"]
