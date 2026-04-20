from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.kb_chat_agentic.preprocess_context_nodes import merge_context
from app.core.settings import Settings


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={}, store=None)


@pytest.mark.asyncio
async def test_merge_context_trims_history_messages_by_token_budget_but_keeps_latest_question() -> None:
    settings = Settings(
        CONTEXT_HISTORY_MAX_TOKENS=6,
        SUMMARY_ENABLED=False,
        MEMORY_ENABLED=False,
    )

    result = await merge_context(
        {
            "user_input": "最后问题",
            "messages": [
                HumanMessage(content="第一问 第一问 第一问 第一问"),
                AIMessage(content="第一答 第一答 第一答 第一答"),
                HumanMessage(content="第二问 第二问 第二问"),
                AIMessage(content="第二答 第二答 第二答"),
                HumanMessage(content="最后问题"),
            ],
            "metrics": {},
            "stage_summaries": {},
        },
        _runtime(),
        settings,
    )

    context_frame = result["context_frame"]
    selected_turns = context_frame["selected_turns"]

    assert result["rewrite_input_query"] == "最后问题"
    assert all("第一问" not in turn["text"] for turn in selected_turns)
    assert "最后问题" in result["merged_context"]
    assert (
        result["stage_summaries"]["merge_context"]["history_trimmed"] is True
    )


@pytest.mark.asyncio
async def test_merge_context_preserves_persisted_summary_system_message_when_trimming() -> None:
    settings = Settings(
        CONTEXT_HISTORY_MAX_TOKENS=4,
        SUMMARY_ENABLED=False,
        MEMORY_ENABLED=False,
    )

    result = await merge_context(
        {
            "user_input": "当前问题",
            "messages": [
                SystemMessage(content="对话摘要：\n之前已经确认过部署窗口。"),
                HumanMessage(content="很早之前的问题 很早之前的问题 很早之前的问题"),
                AIMessage(content="很早之前的回答 很早之前的回答 很早之前的回答"),
                HumanMessage(content="当前问题"),
            ],
            "metrics": {},
            "stage_summaries": {},
        },
        _runtime(),
        settings,
    )

    context_frame = result["context_frame"]

    assert context_frame["summary_source"] == "persisted"
    assert context_frame["summary_text"] == "之前已经确认过部署窗口。"
    assert "对话摘要：" in result["merged_context"]
    assert result["stage_summaries"]["merge_context"]["history_trimmed"] is True
