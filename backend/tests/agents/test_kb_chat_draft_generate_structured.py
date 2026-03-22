from __future__ import annotations

from types import SimpleNamespace

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


class _FakePlainRunnable:
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
        plain_response: object | None = None,
        plain_invoke_error: Exception | None = None,
    ) -> None:
        self._response = response
        self._invoke_error = invoke_error
        self._structured_output_error = structured_output_error
        self._plain_response = plain_response
        self._plain_invoke_error = plain_invoke_error
        self.structured_calls: list[tuple[object, dict[str, object]]] = []
        self.structured_runnable: _FakeStructuredRunnable | None = None
        self.plain_requests: list[object] = []
        self.bound_kwargs: dict[str, object] | None = None
        self.plain_runnable: _FakePlainRunnable | None = None

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

    def bind(self, **kwargs: object) -> _FakePlainRunnable:
        self.bound_kwargs = dict(kwargs)
        self.plain_runnable = _FakePlainRunnable(
            self._plain_response,
            invoke_error=self._plain_invoke_error,
        )
        return self.plain_runnable

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
async def test_generate_draft_recovers_empty_structured_paragraphs_via_plain_text_projection() -> None:
    fake_model = _FakeChatModel(
        DraftAnswerDecision(paragraphs=[]),
        plain_response=SimpleNamespace(
            content=(
                "核心区别在于：Agentic AI 具备决策结构，会围绕目标主动规划、执行和调整；"
                "传统 LLM 通常是接收输入后直接生成回答。[S1]\n\n"
                "四大核心组件正是这种差异的支撑机制：任务规划器负责拆解目标并安排执行顺序；"
                "工具调用系统负责调用外部 API；记忆模块负责记录上下文和状态；"
                "控制策略负责决定重试、等待用户输入或终止。[S1][S2]"
            )
        ),
    )

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.bound_kwargs == {"max_tokens": 1024}
    assert fake_model.plain_runnable is not None
    assert len(fake_model.plain_runnable.requests) == 1
    assert updates["answer_render_meta"]["paragraph_count"] == 2
    assert len(updates["answer_paragraphs"]) == 2
    assert updates["draft_answer"].startswith("核心区别在于：Agentic AI 具备决策结构")
    assert "任务规划器负责拆解目标并安排执行顺序" in updates["draft_answer"]
    assert updates["draft_answer"].endswith("[S1][S2]")
    assert (
        updates["stage_summaries"]["generator"]["fallback_reason"]
        == "empty_structured_paragraphs_recovered_by_plain_text_projection"
    )


@pytest.mark.asyncio
async def test_generate_draft_recovers_empty_structured_response_via_plain_text_projection() -> None:
    fake_model = _FakeChatModel(
        None,
        plain_response=SimpleNamespace(
            content="Agentic AI 的四大核心组件包括任务规划器、工具调用系统、记忆模块和控制策略。[S1][S2]"
        ),
    )

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.bound_kwargs == {"max_tokens": 1024}
    assert fake_model.plain_runnable is not None
    assert len(fake_model.plain_runnable.requests) == 1
    assert updates["draft_answer"] == "Agentic AI 的四大核心组件包括任务规划器、工具调用系统、记忆模块和控制策略。[S1][S2]"
    assert updates["answer_render_meta"]["paragraph_count"] == 1
    assert (
        updates["stage_summaries"]["generator"]["fallback_reason"]
        == "empty_structured_response_recovered_by_plain_text_projection"
    )


@pytest.mark.asyncio
async def test_generate_draft_plain_text_projection_merges_uncited_heading_into_following_cited_block() -> None:
    fake_model = _FakeChatModel(
        None,
        plain_response=SimpleNamespace(
            content=(
                "AI Agent 使用工具 / Function Calling 的完整六步流程如下：\n\n"
                "1. 任务判断：先判断是否需要使用工具。\n"
                "2. 工具选择：从工具库中选择合适工具。\n"
                "3. 参数准备：生成结构化输入参数。\n"
                "4. 工具调用：通过 API 或函数执行方式调用工具。\n"
                "5. 结果获取与处理：接收工具返回结果并处理异常。\n"
                "6. 结果整合与下一步规划：将结果融入思维链并规划下一步。[S1][S2]"
            )
        ),
    )

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert updates["answer_render_meta"]["paragraph_count"] == 1
    assert len(updates["answer_paragraphs"]) == 1
    assert updates["answer_paragraphs"][0]["citation_ids"] == ["S1", "S2"]
    assert updates["answer_paragraphs"][0]["text"].startswith(
        "AI Agent 使用工具 / Function Calling 的完整六步流程如下："
    )
    assert updates["draft_answer"].endswith("[S1][S2]")


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
