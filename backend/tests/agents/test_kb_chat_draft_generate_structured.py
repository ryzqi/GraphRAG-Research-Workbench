from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage

from app.agents.kb_chat_agentic import reflection as reflection_module
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


def _build_multi_entity_state() -> dict[str, object]:
    return {
        "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
        "final_context": (
            "[S1] Embedding 模型负责海选阶段（召回），快速从海量信息中捕获候选项。\n"
            "[S2] Embedding 模型采用双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动。\n"
            "[S3] Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分。\n"
            "[S4] Re-rank 模型采用交叉编码器（Cross-Encoder），主要挑战是算力与性能的平衡。"
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
        (DraftAnswerDecision, {"method": "function_calling", "include_raw": True})
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
async def test_generate_draft_autofills_missing_paragraph_ids_from_raw_json_structured_output() -> None:
    fake_model = _FakeChatModel(
        {
            "raw": AIMessage(
                content=(
                    "{"
                    '"paragraphs":['
                    "{"
                    '"text":"CoT 适合单路径、步骤明确的推理任务。",'
                    '"citation_ids":["S1"],'
                    '"claims":['
                    "{"
                    '"claim_id":"c1",'
                    '"claim_text":"CoT 适合单路径、步骤明确的推理任务。",'
                    '"role":"main",'
                    '"support_status":"supported",'
                    '"supporting_citation_ids":["S1"]'
                    "}"
                    "]"
                    "}"
                    "]"
                    "}"
                )
            ),
            "parsed": None,
            "parsing_error": None,
        }
    )

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert updates["draft_answer"] == "CoT 适合单路径、步骤明确的推理任务。[S1]"
    assert updates["answer_paragraphs"][0]["paragraph_id"] == "p1"
    assert updates["answer_render_meta"]["claim_count"] == 1
    assert updates["stage_summaries"]["generator"]["fallback_reason"] is None
    assert fake_model.plain_runnable is None


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
async def test_generate_draft_parses_raw_tool_call_args_when_parser_returns_none() -> None:
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "DraftAnswerDecision",
                "args": {
                    "paragraphs": [
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
                },
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.structured_calls == [
        (DraftAnswerDecision, {"method": "function_calling", "include_raw": True})
    ]
    assert updates["draft_answer"] == "CoT 更适合单路径、步骤明确的推理任务。[S1][S2]"
    assert updates["final_answer"] == updates["draft_answer"]
    assert updates["answer_render_meta"]["paragraph_count"] == 1
    assert updates["stage_summaries"]["generator"]["fallback_reason"] is None
    assert fake_model.plain_runnable is None


@pytest.mark.asyncio
async def test_generate_draft_parses_tool_use_content_blocks_when_parser_returns_none() -> None:
    raw_message = AIMessage(
        content=[
            {
                "type": "tool_use",
                "name": "DraftAnswerDecision",
                "input": {
                    "paragraphs": [
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
                },
            }
        ]
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert updates["draft_answer"] == "CoT 更适合单路径、步骤明确的推理任务。[S1][S2]"
    assert updates["final_answer"] == updates["draft_answer"]
    assert updates["answer_render_meta"]["paragraph_count"] == 1
    assert updates["stage_summaries"]["generator"]["fallback_reason"] is None
    assert fake_model.plain_runnable is None


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
async def test_generate_draft_prompts_include_multi_entity_coverage_checklist_for_structured_and_plain_fallback() -> None:
    fake_model = _FakeChatModel(
        DraftAnswerDecision(paragraphs=[]),
        plain_response=SimpleNamespace(
            content=(
                "Embedding 模型负责海选阶段（召回），技术架构是双塔结构（Dual-Encoder），"
                "挑战是向量表达对齐与冷启动。[S1][S2]\n\n"
                "Re-rank 模型负责决赛阶段（排序），技术架构是交叉编码器（Cross-Encoder），"
                "挑战是算力与性能的平衡。[S3][S4]"
            )
        ),
    )

    await generate_draft(
        _build_multi_entity_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.structured_runnable is not None
    structured_request = fake_model.structured_runnable.requests[0]
    structured_prompt = structured_request[1].content
    assert "覆盖清单：" in structured_prompt
    assert (
        "- Embedding 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：召回 / Dual-Encoder"
        in structured_prompt
    )
    assert (
        "- Re-rank 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：排序 / Cross-Encoder"
        in structured_prompt
    )
    assert "不得把整实体写成“资料不足”" in structured_prompt

    assert fake_model.plain_runnable is not None
    plain_request = fake_model.plain_runnable.requests[0]
    plain_prompt = plain_request[1].content
    assert "覆盖清单：" in plain_prompt
    assert (
        "- Embedding 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：召回 / Dual-Encoder"
        in plain_prompt
    )
    assert (
        "- Re-rank 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：排序 / Cross-Encoder"
        in plain_prompt
    )
    assert "不得把整实体写成“资料不足”" in plain_prompt


@pytest.mark.asyncio
async def test_generate_draft_locally_repairs_multi_entity_term_gap_with_plain_projection() -> None:
    bad_structured = DraftAnswerDecision(
        paragraphs=[
            AnswerParagraph(
                paragraph_id="p1",
                text="Embedding模型负责海选阶段（召回），快速从海量信息中捕获候选项。参考内容未提供Embedding模型的技术架构信息。",
                citation_ids=["S1"],
                claims=[
                    ParagraphClaim(
                        claim_id="c1",
                        claim_text="Embedding模型负责海选阶段（召回），快速从海量信息中捕获候选项。",
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S1"],
                    )
                ],
                review_status="passed",
            ),
            AnswerParagraph(
                paragraph_id="p2",
                text="Re-rank模型负责决赛阶段（排序），技术架构是交叉编码器（Cross-Encoder）。",
                citation_ids=["S3", "S4"],
                claims=[
                    ParagraphClaim(
                        claim_id="c2",
                        claim_text="Re-rank模型负责决赛阶段（排序），技术架构是交叉编码器（Cross-Encoder）。",
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S3", "S4"],
                    )
                ],
                review_status="passed",
            ),
        ]
    )
    fake_model = _FakeChatModel(
        bad_structured,
        plain_response=SimpleNamespace(
            content=(
                "Embedding 模型负责海选阶段（召回），技术架构是双塔结构（Dual-Encoder），"
                "挑战是向量表达对齐与冷启动。[S1][S2]\n\n"
                "Re-rank 模型负责决赛阶段（排序），技术架构是交叉编码器（Cross-Encoder），"
                "挑战是算力与性能的平衡。[S3][S4]"
            )
        ),
    )

    updates = await generate_draft(
        _build_multi_entity_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert fake_model.structured_runnable is not None
    assert fake_model.plain_runnable is not None
    assert "Dual-Encoder" in updates["draft_answer"]
    assert "Cross-Encoder" in updates["draft_answer"]
    assert "参考内容未提供Embedding模型的技术架构信息" not in updates["draft_answer"]
    assert updates["answer_render_meta"]["paragraph_count"] == 2
    assert updates["stage_summaries"]["generator"]["fallback_reason"] is None


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
async def test_generate_draft_plain_text_projection_normalizes_fullwidth_citations_and_hyphen_variants() -> None:
    fake_model = _FakeChatModel(
        None,
        plain_response=SimpleNamespace(
            content="Re‑rank 模型负责精排候选结果，并通过交叉编码器做深度匹配。【S1】【S2】"
        ),
    )

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=fake_model,
    )

    assert updates["answer_render_meta"]["paragraph_count"] == 1
    assert updates["answer_paragraphs"][0]["citation_ids"] == ["S1", "S2"]
    assert updates["answer_paragraphs"][0]["text"] == "Re-rank 模型负责精排候选结果，并通过交叉编码器做深度匹配。"
    assert updates["draft_answer"] == "Re-rank 模型负责精排候选结果，并通过交叉编码器做深度匹配。[S1][S2]"


@pytest.mark.asyncio
async def test_generate_draft_retries_structured_with_fresh_model_after_invoke_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_model = _FakeChatModel(
        response=None,
        invoke_error=RuntimeError("structured invoke failed"),
    )
    retry_payload = DraftAnswerDecision(
        paragraphs=[
            AnswerParagraph(
                paragraph_id="p1",
                text="CoT 的主要变体包括零样本思维链、自动思维链和多模态思维链。",
                citation_ids=["S1"],
                claims=[
                    ParagraphClaim(
                        claim_id="c1",
                        claim_text="CoT 的主要变体包括零样本思维链、自动思维链和多模态思维链。",
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S1"],
                    )
                ],
                review_status="passed",
            )
        ]
    )
    retry_model = _FakeChatModel(retry_payload)
    create_calls: list[tuple[Settings, bool | None]] = []

    def _fake_create_chat_model(*, settings: Settings | None = None, use_previous_response_id: bool | None = None) -> _FakeChatModel:
        assert settings is not None
        create_calls.append((settings, use_previous_response_id))
        return retry_model

    monkeypatch.setattr(reflection_module, "create_chat_model", _fake_create_chat_model)

    updates = await generate_draft(
        _build_state(),
        settings=Settings(),
        chat_model=primary_model,
    )

    assert primary_model.structured_runnable is not None
    assert retry_model.structured_runnable is not None
    assert create_calls and create_calls[0][1] is False
    assert updates["draft_answer"] == "CoT 的主要变体包括零样本思维链、自动思维链和多模态思维链。[S1]"
    assert updates["final_answer"] == updates["draft_answer"]
    assert updates["answer_render_meta"]["paragraph_count"] == 1
    assert updates["stage_summaries"]["generator"]["fallback_reason"] is None
    assert primary_model.plain_runnable is None
    assert retry_model.plain_runnable is None


@pytest.mark.asyncio
async def test_generate_draft_retries_structured_with_fresh_model_after_empty_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_model = _FakeChatModel(None)
    retry_payload = DraftAnswerDecision(
        paragraphs=[
            AnswerParagraph(
                paragraph_id="p1",
                text=(
                    "Embedding 模型负责海选阶段（召回），采用双塔结构（Dual-Encoder），"
                    "主要挑战是向量表达对齐与冷启动。"
                ),
                citation_ids=["S1", "S2"],
                claims=[
                    ParagraphClaim(
                        claim_id="c1",
                        claim_text=(
                            "Embedding 模型负责海选阶段（召回），采用双塔结构（Dual-Encoder），"
                            "主要挑战是向量表达对齐与冷启动。"
                        ),
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S1", "S2"],
                    )
                ],
                review_status="passed",
            ),
            AnswerParagraph(
                paragraph_id="p2",
                text=(
                    "Re-rank 模型负责决赛阶段（排序），采用交叉编码器（Cross-Encoder），"
                    "主要挑战是算力与性能的平衡。"
                ),
                citation_ids=["S3", "S4"],
                claims=[
                    ParagraphClaim(
                        claim_id="c2",
                        claim_text=(
                            "Re-rank 模型负责决赛阶段（排序），采用交叉编码器（Cross-Encoder），"
                            "主要挑战是算力与性能的平衡。"
                        ),
                        role="main",
                        support_status="supported",
                        supporting_citation_ids=["S3", "S4"],
                    )
                ],
                review_status="passed",
            ),
        ]
    )
    retry_model = _FakeChatModel(retry_payload)

    def _fake_create_chat_model(*, settings: Settings | None = None, use_previous_response_id: bool | None = None) -> _FakeChatModel:
        assert settings is not None
        assert use_previous_response_id is False
        return retry_model

    monkeypatch.setattr(reflection_module, "create_chat_model", _fake_create_chat_model)

    updates = await generate_draft(
        _build_multi_entity_state(),
        settings=Settings(),
        chat_model=primary_model,
    )

    assert primary_model.structured_runnable is not None
    assert retry_model.structured_runnable is not None
    assert updates["answer_render_meta"]["paragraph_count"] == 2
    assert "Dual-Encoder" in updates["draft_answer"]
    assert "Cross-Encoder" in updates["draft_answer"]
    assert "向量表达对齐与冷启动" in updates["draft_answer"]
    assert "算力与性能的平衡" in updates["draft_answer"]
    assert updates["stage_summaries"]["generator"]["fallback_reason"] is None
    assert primary_model.plain_runnable is None
    assert retry_model.plain_runnable is None


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
        (DraftAnswerDecision, {"method": "function_calling", "include_raw": True})
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
