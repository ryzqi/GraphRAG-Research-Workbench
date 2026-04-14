from __future__ import annotations

import importlib
import importlib.util

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from app.integrations.llm_client import ChatMessage


def _load_context_seed_module():
    spec = importlib.util.find_spec("app.services.kb_chat_context_seed")
    assert spec is not None, "shared kb_chat context seed module is missing"
    return importlib.import_module("app.services.kb_chat_context_seed")


def test_history_and_messages_build_same_seed_for_current_turn_lookup() -> None:
    context_seed = _load_context_seed_module()
    summary_text = "用户已经确认比较范围。"
    current_question = "继续比较它们的差异"

    history_seed = context_seed.build_context_seed_from_history(
        summary_text=summary_text,
        history=[
            ChatMessage(role="user", content="先介绍 A"),
            ChatMessage(role="assistant", content="这是 A"),
            ChatMessage(role="user", content="再介绍 B"),
            ChatMessage(role="assistant", content="这是 B"),
        ],
        question=current_question,
        max_turns=6,
    )

    message_seed = context_seed.build_context_seed_from_messages(
        summary_text=summary_text,
        messages=[
            SystemMessage(content="你是知识库问答助手"),
            SystemMessage(content=f"对话摘要：\n{summary_text}"),
            HumanMessage(content="先介绍 A"),
            AIMessage(content="这是 A"),
            HumanMessage(content="再介绍 B"),
            AIMessage(content="这是 B"),
            HumanMessage(content=current_question),
        ],
        question=current_question,
        max_turns=6,
        exclude_question=current_question,
    )

    assert message_seed == history_seed
    assert context_seed.context_seed_turns_to_context_frame_turns(
        message_seed["recent_turns"]
    ) == [
        {"role": "user", "text": "先介绍 A"},
        {"role": "assistant", "text": "这是 A"},
        {"role": "user", "text": "再介绍 B"},
        {"role": "assistant", "text": "这是 B"},
    ]
