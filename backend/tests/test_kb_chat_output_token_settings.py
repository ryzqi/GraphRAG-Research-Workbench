from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage

from app.agents.kb_chat_agentic.answer_subgraph_finalize import _answer_repair
from app.agents.kb_chat_agentic.output_token_budget import (
    resolve_kb_chat_draft_max_tokens,
    resolve_kb_chat_plain_fallback_max_tokens,
    resolve_kb_chat_repair_max_tokens,
)
from app.agents.kb_chat_agentic.reflection_draft_generation import generate_draft
from app.agents.kb_chat_agentic.reflection_draft_utils import (
    _attempt_local_plain_text_draft_repair,
)
from app.core.settings import Settings


class _StructuredFailureModel:
    async def ainvoke(self, _messages):
        return None


class _RecordingChatModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.bound_max_tokens: list[int] = []

    def bind(self, **kwargs):
        self.bound_max_tokens.append(kwargs["max_tokens"])
        return self

    def with_structured_output(self, *_args, **_kwargs):
        return _StructuredFailureModel()

    async def ainvoke(self, _messages):
        return AIMessage(content=self.content)


def test_kb_chat_output_token_settings_defaults_and_resolvers() -> None:
    fields = Settings.model_fields
    settings = Settings()

    assert fields["kb_chat_draft_max_tokens"].default == 2_048
    assert fields["kb_chat_repair_max_tokens"].default == 1_500
    assert fields["kb_chat_plain_fallback_max_tokens"].default == 1_500
    assert resolve_kb_chat_draft_max_tokens("simple", settings) == 2_048
    assert resolve_kb_chat_draft_max_tokens("moderate", settings) == 2_560
    assert resolve_kb_chat_draft_max_tokens("complex", settings) == 3_072
    assert resolve_kb_chat_repair_max_tokens(settings) == 1_500
    assert resolve_kb_chat_plain_fallback_max_tokens(settings) == 1_500


def test_resolve_kb_chat_draft_max_tokens_rejects_unknown_complexity() -> None:
    with pytest.raises(ValueError, match="Unsupported KB Chat complexity_level"):
        resolve_kb_chat_draft_max_tokens("unknown", Settings())


def test_kb_chat_output_token_settings_reject_non_positive_values() -> None:
    with pytest.raises(ValueError):
        Settings(KB_CHAT_DRAFT_MAX_TOKENS=0)
    with pytest.raises(ValueError):
        Settings(KB_CHAT_REPAIR_MAX_TOKENS=0)
    with pytest.raises(ValueError):
        Settings(KB_CHAT_PLAIN_FALLBACK_MAX_TOKENS=0)


@pytest.mark.asyncio
async def test_generate_draft_uses_complexity_draft_budget_and_plain_fallback_budget() -> None:
    settings = Settings(
        KB_CHAT_DRAFT_MAX_TOKENS=100,
        KB_CHAT_PLAIN_FALLBACK_MAX_TOKENS=77,
    )
    model = _RecordingChatModel("回答内容 [S1]")

    result = await generate_draft(
        {
            "normalized_query": "问题",
            "complexity_level": "complex",
            "final_context": "[S1] 参考内容",
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
        },
        settings=settings,
        chat_model=model,
    )

    assert model.bound_max_tokens == [150, 77]
    assert "回答内容" in result["draft_answer"]
    assert "[S1]" in result["draft_answer"]


@pytest.mark.asyncio
async def test_local_plain_text_draft_repair_uses_repair_token_budget() -> None:
    settings = Settings(KB_CHAT_REPAIR_MAX_TOKENS=88)
    model = _RecordingChatModel("修复后答案 [S1]")

    repaired = await _attempt_local_plain_text_draft_repair(
        chat_model=model,
        settings=settings,
        system_prompt="system",
        question="问题",
        final_context="[S1] 参考内容",
        coverage_block="",
        draft="原答案",
        coverage_gap={"reason": "incomplete", "missing_entities": ["A"]},
    )

    assert model.bound_max_tokens == [88]
    assert repaired is not None


@pytest.mark.asyncio
async def test_answer_repair_uses_repair_token_budget() -> None:
    settings = Settings(KB_CHAT_REPAIR_MAX_TOKENS=88)
    model = _RecordingChatModel("修复后答案 [S1]")

    await _answer_repair(
        {
            "normalized_query": "问题",
            "draft_answer": "原答案 [S1]",
            "final_context": "[S1] 参考内容",
            "loop_counts": {
                "total_rounds": 1,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "answer_subgraph_state": {},
        },
        SimpleNamespace(),
        settings=settings,
        chat_model=model,
    )

    assert model.bound_max_tokens == [88]
