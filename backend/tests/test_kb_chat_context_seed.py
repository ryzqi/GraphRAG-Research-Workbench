from __future__ import annotations

import importlib
import importlib.util

from app.integrations.llm_client import ChatMessage
from app.services.semantic_cache.policy import build_context_signature


def _load_context_seed_module():
    spec = importlib.util.find_spec("app.services.kb_chat_context_seed")
    assert spec is not None, "shared kb_chat context seed module is missing"
    return importlib.import_module("app.services.kb_chat_context_seed")


def test_build_context_seed_from_history_excludes_current_turn_and_trims() -> None:
    context_seed = _load_context_seed_module()

    seed = context_seed.build_context_seed_from_history(
        summary_text="  已知用户已经确认部署方案。  ",
        history=[
            ChatMessage(role="user", content="第一轮问题"),
            ChatMessage(role="assistant", content="第一轮回答"),
            ChatMessage(role="user", content="第二轮问题"),
            ChatMessage(role="assistant", content="第二轮回答"),
            ChatMessage(role="user", content="第三轮问题"),
            ChatMessage(role="assistant", content="第三轮回答"),
            ChatMessage(role="user", content="当前问题"),
            ChatMessage(role="assistant", content="当前回答"),
        ],
        question="当前问题",
        current_answer="当前回答",
        max_turns=2,
    )

    assert seed == {
        "summary_text": "已知用户已经确认部署方案。",
        "recent_turns": [
            {"role": "user", "content": "第二轮问题"},
            {"role": "assistant", "content": "第二轮回答"},
            {"role": "user", "content": "第三轮问题"},
            {"role": "assistant", "content": "第三轮回答"},
        ],
        "question": "当前问题",
    }


def test_context_signature_ignores_question_but_uses_shared_seed_shape() -> None:
    context_seed = _load_context_seed_module()

    seed_a = context_seed.build_context_seed_from_history(
        summary_text="摘要",
        history=[
            ChatMessage(role="user", content="上一问"),
            ChatMessage(role="assistant", content="上一答"),
        ],
        question="继续展开",
        max_turns=3,
    )
    seed_b = context_seed.build_context_seed_from_history(
        summary_text="摘要",
        history=[
            ChatMessage(role="user", content="上一问"),
            ChatMessage(role="assistant", content="上一答"),
        ],
        question="换个问法继续展开",
        max_turns=3,
    )

    assert seed_a["question"] != seed_b["question"]
    assert seed_a["recent_turns"] == seed_b["recent_turns"]
    assert build_context_signature(seed_a) == build_context_signature(seed_b)
