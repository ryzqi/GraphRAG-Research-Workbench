from __future__ import annotations

import pytest

from app.agents.kb_chat_agentic.reflection import generate_draft
from app.agents.kb_chat_agentic.schemas import (
    AnswerParagraph,
    DraftAnswerDecision,
    ParagraphClaim,
)
from app.core.settings import Settings
from app.services.kb_answer_paragraphs import render_answer_paragraphs


class _FakeStructuredRunnable:
    def __init__(
        self,
        response: object | None,
        *,
        invoke_error: Exception | None = None,
    ) -> None:
        self._response = response
        self._invoke_error = invoke_error
        self.requests: list[object] = []

    async def ainvoke(self, request: object) -> object:
        self.requests.append(request)
        if self._invoke_error is not None:
            raise self._invoke_error
        return self._response


class _FakeChatModel:
    def __init__(
        self,
        response: object | None,
        *,
        invoke_error: Exception | None = None,
        structured_output_error: Exception | None = None,
    ) -> None:
        self._response = response
        self._invoke_error = invoke_error
        self._structured_output_error = structured_output_error
        self.structured_calls: list[tuple[object, dict[str, object]]] = []
        self.structured_runnable: _FakeStructuredRunnable | None = None
        self.plain_requests: list[object] = []

    def with_structured_output(
        self, schema: object, /, **kwargs: object
    ) -> _FakeStructuredRunnable:
        self.structured_calls.append((schema, kwargs))
        if self._structured_output_error is not None:
            raise self._structured_output_error
        self.structured_runnable = _FakeStructuredRunnable(
            self._response,
            invoke_error=self._invoke_error,
        )
        return self.structured_runnable

    async def ainvoke(self, request: object) -> object:
        self.plain_requests.append(request)
        raise AssertionError("generate_draft 不应回退到 plain ainvoke")


def _build_state() -> dict[str, object]:
    return {
        "user_input": "请说明 CoT 的适用场景。",
        "final_context": (
            "[S1] CoT 适合单路径、步骤明确的推理任务。\n"
            "[S2] 当问题需要多个分支探索时，Tree of Thoughts 通常更灵活。"
        ),
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
    }


@pytest.mark.asyncio
async def test_generate_draft_returns_state_friendly_structured_paragraphs_and_rendered_text() -> None:
    payload = DraftAnswerDecision(
        paragraphs=[
            AnswerParagraph(
                paragraph_id="p1",
                text="CoT 更适合单路径、步骤明确的推理任务。",
                citation_ids=["S1", "S2"],
                claims=[
                    ParagraphClaim(
                        claim_id="c1",
                        claim_text="CoT 更适合单路径、步骤明确的推理任务。",
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S1", "S2"],
                    )
                ],
                review_status="passed",
            )
        ]
    )
    fake_model = _FakeChatModel(payload)

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.structured_calls == [
        (DraftAnswerDecision, {"method": "function_calling"})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1
    assert fake_model.plain_requests == []

    assert isinstance(updates["answer_paragraphs"], list)
    assert updates["answer_paragraphs"][0]["citation_ids"] == ["S1", "S2"]
    assert isinstance(updates["answer_paragraphs"][0], dict)
    assert isinstance(updates["answer_paragraphs"][0]["claims"][0], dict)

    rendered = render_answer_paragraphs(updates["answer_paragraphs"])
    assert updates["draft_answer"] == rendered
    assert updates["draft_answer"].endswith("[S1][S2]")
    assert updates["final_answer"] == updates["draft_answer"]

    assert updates["answer_render_meta"] == {
        "paragraph_count": 1,
        "claim_count": 1,
        "citation_count": 2,
        "citation_mode": "paragraph_aggregate",
    }
    assert isinstance(updates["answer_render_meta"], dict)

    assert updates["stage_summaries"]["generator"]["paragraph_count"] == 1
    assert updates["stage_summaries"]["generator"]["claim_count"] == 1
    assert updates["stage_summaries"]["generator"]["citation_mode"] == "paragraph_aggregate"
    assert updates["stage_summaries"]["draft_generate"]["paragraph_count"] == 1
    assert updates["stage_summaries"]["draft_generate"]["claim_count"] == 1
    assert updates["loop_counts"]["total_rounds"] == 1


@pytest.mark.asyncio
async def test_generate_draft_normalizes_state_paragraphs_meta_and_render_output() -> None:
    payload = DraftAnswerDecision(
        paragraphs=[
            AnswerParagraph(
                paragraph_id="p1",
                text="CoT 更适合单路径、步骤明确的推理任务。",
                citation_ids=["S9", "S1"],
                claims=[
                    ParagraphClaim(
                        claim_id="c1",
                        claim_text="CoT 更适合单路径、步骤明确的推理任务。",
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S1", "S2"],
                    )
                ],
                review_status="passed",
            )
        ]
    )
    fake_model = _FakeChatModel(payload)

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert updates["answer_paragraphs"] == [
        {
            "paragraph_id": "p1",
            "text": "CoT 更适合单路径、步骤明确的推理任务。",
            "citation_ids": ["S1", "S2"],
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "CoT 更适合单路径、步骤明确的推理任务。",
                    "role": "main",
                    "support_status": "supported",
                    "supporting_citation_ids": ["S1", "S2"],
                }
            ],
            "review_status": "passed",
        }
    ]
    assert updates["answer_render_meta"] == {
        "paragraph_count": 1,
        "claim_count": 1,
        "citation_count": 2,
        "citation_mode": "paragraph_aggregate",
    }
    assert updates["draft_answer"] == "CoT 更适合单路径、步骤明确的推理任务。[S1][S2]"
    assert updates["final_answer"] == updates["draft_answer"]


@pytest.mark.asyncio
async def test_generate_draft_treats_empty_structured_paragraphs_as_safe_no_answer() -> None:
    fake_model = _FakeChatModel(DraftAnswerDecision(paragraphs=[]))

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert updates["draft_answer"] == "根据现有资料无法回答该问题。"
    assert updates["final_answer"] == updates["draft_answer"]
    assert updates["answer_paragraphs"] == []
    assert updates["answer_render_meta"] == {
        "paragraph_count": 0,
        "claim_count": 0,
        "citation_count": 0,
        "citation_mode": "paragraph_aggregate",
    }
    assert updates["stage_summaries"]["generator"]["fallback_reason"] == "empty_structured_paragraphs"
    assert updates["stage_summaries"]["draft_generate"]["paragraph_count"] == 0


@pytest.mark.asyncio
async def test_generate_draft_falls_back_safely_when_structured_invoke_fails() -> None:
    fake_model = _FakeChatModel(
        response=None,
        invoke_error=RuntimeError("structured invoke failed"),
    )

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.structured_calls == [
        (DraftAnswerDecision, {"method": "function_calling"})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1
    assert fake_model.plain_requests == []

    assert updates["draft_answer"] == "根据现有资料无法回答该问题（生成失败）。"
    assert updates["final_answer"] == updates["draft_answer"]
    assert updates["answer_paragraphs"] == []
    assert updates["answer_render_meta"] == {
        "paragraph_count": 0,
        "claim_count": 0,
        "citation_count": 0,
        "citation_mode": "paragraph_aggregate",
    }
    assert updates["stage_summaries"]["generator"]["fallback_reason"] == "structured_invoke_failed"
    assert updates["stage_summaries"]["draft_generate"]["paragraph_count"] == 0
