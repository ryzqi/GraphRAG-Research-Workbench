from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage

from app.agents.kb_chat_agentic import answer_subgraph
from app.agents.kb_chat_agentic.schemas import AnswerReviewSubDecision
from app.core.settings import Settings


def _build_citation_catalog(*citation_ids: str) -> dict[str, dict[str, str]]:
    return {
        citation_id: {
            "citation_id": citation_id,
            "excerpt": f"evidence for {citation_id}",
        }
        for citation_id in citation_ids
    }


def _build_state() -> dict[str, object]:
    return {
        "user_input": "请说明 CoT 的适用场景。",
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。[S1][S2]",
        "final_context": (
            "[S1] CoT 适合单路径、步骤明确的推理任务。\n"
            "[S2] 当问题需要多个分支探索时，Tree of Thoughts 通常更灵活。"
        ),
        "citation_catalog": _build_citation_catalog("S1", "S2"),
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
    }


class _FakeReviewStructuredRunnable:
    def __init__(self, response: object) -> None:
        self._response = response
        self.requests: list[object] = []

    async def ainvoke(self, request: object) -> object:
        self.requests.append(request)
        return self._response


class _FakeReviewModel:
    def __init__(self, response: object) -> None:
        self._response = response
        self.structured_calls: list[tuple[object, dict[str, object]]] = []
        self.structured_runnable: _FakeReviewStructuredRunnable | None = None

    def with_structured_output(
        self, schema: object, /, **kwargs: object
    ) -> _FakeReviewStructuredRunnable:
        self.structured_calls.append((schema, dict(kwargs)))
        self.structured_runnable = _FakeReviewStructuredRunnable(self._response)
        return self.structured_runnable


@pytest.mark.asyncio
async def test_judge_structured_uses_function_calling_include_raw_and_raw_payload_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model = _FakeReviewModel(
        {
            "raw": AIMessage(
                content=(
                    '{"passed": true, "reason": "passed", "confidence": 0.94, '
                    '"missing_citations": [], "unsupported_claims": [], '
                    '"affected_paragraph_ids": [], "details": {}}'
                )
            ),
            "parsed": None,
            "parsing_error": None,
        }
    )
    monkeypatch.setattr(
        answer_subgraph,
        "create_agent",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("answer_review 不应再走 create_agent(response_format) 路径")
        ),
        raising=False,
    )

    decision, fallback_reason = await answer_subgraph._judge_structured(
        chat_model=fake_model,
        system="你是段落回答审查器。",
        user="请审查回答是否满足引用要求。",
    )

    assert fallback_reason is None
    assert decision is not None
    assert decision.passed is True
    assert decision.reason == "passed"
    assert fake_model.structured_calls == [
        (AnswerReviewSubDecision, {"method": "function_calling", "include_raw": True})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1


@pytest.mark.asyncio
async def test_paragraph_citation_review_passes_when_main_claim_matches_aggregate_sources() -> None:
    state = {
        **_build_state(),
        "answer_paragraphs": [
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
        ],
    }

    updates = await answer_subgraph._answer_review_citation(
        state,
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is True
    assert review_run["reason"] == "passed"
    assert review_run["affected_paragraph_ids"] == []
    assert review_run["details"]["paragraph_review_counts"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
    }
    assert review_run["details"]["unsupported_scope"] == "none"


@pytest.mark.asyncio
async def test_paragraph_citation_review_flags_invalid_paragraph_citations() -> None:
    state = {
        **_build_state(),
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。[S9]",
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "CoT 更适合单路径、步骤明确的推理任务。",
                "citation_ids": ["S9"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 更适合单路径、步骤明确的推理任务。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S9"],
                    }
                ],
                "review_status": "failed",
            }
        ],
    }

    updates = await answer_subgraph._answer_review_citation(
        state,
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "invalid_citations"
    assert review_run["affected_paragraph_ids"] == ["p1"]
    assert review_run["details"]["invalid_citation_count"] == 1
    assert review_run["details"]["paragraph_review_counts"]["failed"] == 1


@pytest.mark.asyncio
async def test_paragraph_citation_review_does_not_reclassify_clarification_segment_as_missing_citations() -> None:
    state = {
        **_build_state(),
        "draft_answer": "要判断哪个更高，需先明确你要比较上限还是下限。",
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "要判断哪个更高，需先明确你要比较上限还是下限。",
                "citation_ids": [],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "需要先明确比较口径。",
                        "role": "main",
                        "support_status": "unsupported",
                        "supporting_citation_ids": [],
                    }
                ],
                "review_status": "failed",
            }
        ],
    }

    updates = await answer_subgraph._answer_review_citation(
        state,
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is True
    assert review_run["reason"] == "passed"
    assert review_run["affected_paragraph_ids"] == []
    assert review_run["details"]["paragraph_review_counts"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
    }
    assert review_run["details"]["repair_target_count"] == 0


@pytest.mark.asyncio
async def test_paragraph_citation_review_passes_when_answer_paragraphs_is_empty() -> None:
    state = {
        **_build_state(),
        "draft_answer": "根据现有资料无法回答该问题。",
        "answer_paragraphs": [],
    }

    updates = await answer_subgraph._answer_review_citation(
        state,
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is True
    assert review_run["reason"] == "passed"
    assert review_run["affected_paragraph_ids"] == []
    assert review_run["details"]["paragraph_review_counts"] == {
        "total": 0,
        "passed": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_answer_review_marks_auxiliary_only_unsupported_as_repairable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        **_build_state(),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "CoT 更适合单路径、步骤明确的推理任务。它总能优于 Tree of Thoughts。",
                "citation_ids": ["S1", "S2"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 更适合单路径、步骤明确的推理任务。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S1"],
                    },
                    {
                        "claim_id": "c2",
                        "claim_text": "它总能优于 Tree of Thoughts。",
                        "role": "auxiliary",
                        "support_status": "unsupported",
                        "supporting_citation_ids": ["S2"],
                    },
                ],
                "review_status": "needs_repair",
            }
        ],
    }

    async def _fake_judge_structured(**_: object) -> tuple[AnswerReviewSubDecision, None]:
        return (
            AnswerReviewSubDecision(
                passed=False,
                reason="unsupported_claims",
                confidence=0.92,
                unsupported_claims=["它总能优于 Tree of Thoughts。"],
            ),
            None,
        )

    monkeypatch.setattr(answer_subgraph, "_judge_structured", _fake_judge_structured)

    updates = await answer_subgraph._answer_review(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=SimpleNamespace(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "unsupported_claims"
    assert review_run["affected_paragraph_ids"] == ["p1"]
    assert review_run["details"]["unsupported_scope"] == "auxiliary_only"
    assert review_run["details"]["repair_target_count"] == 1


@pytest.mark.asyncio
async def test_answer_review_prompt_includes_multi_entity_coverage_and_required_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
        "draft_answer": (
            "Embedding 模型负责海选阶段（召回），快速从海量信息中捕获所有可能相关的候选项。"
            "它采用双塔结构（Dual-Encoder），面临的挑战包括向量表达的对齐以及冷启动问题。[S1][S2]\n\n"
            "Re-rank 模型负责决赛阶段（排序），其技术架构为将查询与单个候选项整体输入模型，"
            "主要挑战是算力与性能的平衡。[S3][S4]"
        ),
        "final_context": (
            "[S1] Embedding 模型负责海选阶段（召回），快速从海量信息中捕获候选项。\n"
            "[S2] Embedding 模型采用双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动。\n"
            "[S3] Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分。\n"
            "[S4] Re-rank 模型采用交叉编码器（Cross-Encoder），主要挑战是算力与性能的平衡。"
        ),
        "citation_catalog": _build_citation_catalog("S1", "S2", "S3", "S4"),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "Embedding 模型负责海选阶段（召回），快速从海量信息中捕获所有可能相关的候选项。它采用双塔结构（Dual-Encoder），面临的挑战包括向量表达的对齐以及冷启动问题。",
                "citation_ids": ["S1", "S2"],
                "claims": [],
                "review_status": "passed",
            },
            {
                "paragraph_id": "p2",
                "text": "Re-rank 模型负责决赛阶段（排序），其技术架构为将查询与单个候选项整体输入模型，主要挑战是算力与性能的平衡。",
                "citation_ids": ["S3", "S4"],
                "claims": [],
                "review_status": "passed",
            },
        ],
        "stage_summaries": {},
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
    }
    captured: dict[str, object] = {}

    async def _fake_judge_structured(**kwargs: object) -> tuple[AnswerReviewSubDecision, None]:
        captured.update(kwargs)
        return (
            AnswerReviewSubDecision(
                passed=False,
                reason="incomplete",
                confidence=0.95,
                affected_paragraph_ids=["p2"],
            ),
            None,
        )

    monkeypatch.setattr(answer_subgraph, "_judge_structured", _fake_judge_structured)

    await answer_subgraph._answer_review(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=SimpleNamespace(),
    )

    prompt = str(captured["user"])
    assert "覆盖清单：" in prompt
    assert "- Embedding 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：召回 / Dual-Encoder" in prompt
    assert "- Re-rank 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：排序 / Cross-Encoder" in prompt


@pytest.mark.asyncio
async def test_answer_review_overrides_passed_when_multi_entity_answer_only_covers_one_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
        "draft_answer": (
            "Embedding 模型负责海选阶段（召回），快速从海量信息中捕获所有可能相关的候选项；"
            "其技术架构是双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动问题。[S1][S2]"
        ),
        "final_context": (
            "[S1] Embedding 模型负责海选阶段（召回），快速从海量信息中捕获候选项。\n"
            "[S2] Embedding 模型采用双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动。"
        ),
        "citation_catalog": _build_citation_catalog("S1", "S2"),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "Embedding 模型负责海选阶段（召回），快速从海量信息中捕获所有可能相关的候选项；其技术架构是双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动问题。",
                "citation_ids": ["S1", "S2"],
                "claims": [],
                "review_status": "passed",
            }
        ],
        "stage_summaries": {},
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
    }

    async def _fake_judge_structured(**_: object) -> tuple[AnswerReviewSubDecision, None]:
        return (
            AnswerReviewSubDecision(
                passed=True,
                reason="passed",
                confidence=0.91,
                affected_paragraph_ids=[],
            ),
            None,
        )

    monkeypatch.setattr(answer_subgraph, "_judge_structured", _fake_judge_structured)

    updates = await answer_subgraph._answer_review(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=SimpleNamespace(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "incomplete"
    assert review_run["details"]["missing_entities"] == ["Re-rank 模型"]
    assert review_run["details"]["coverage_guardrail"] == "multi_entity_entities"


@pytest.mark.asyncio
async def test_answer_review_overrides_passed_when_required_original_term_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
        "draft_answer": (
            "Embedding 模型负责海选阶段（召回），快速从海量信息中捕获所有可能相关的候选项；"
            "其技术架构是双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动问题。[S1][S2]\n\n"
            "Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分；"
            "其技术架构是将查询与单个候选项整体输入模型，主要挑战是算力与性能的平衡。[S3][S4]"
        ),
        "final_context": (
            "[S1] Embedding 模型负责海选阶段（召回），快速从海量信息中捕获候选项。\n"
            "[S2] Embedding 模型采用双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动。\n"
            "[S3] Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分。\n"
            "[S4] Re-rank 模型采用交叉编码器（Cross-Encoder），主要挑战是算力与性能的平衡。"
        ),
        "citation_catalog": _build_citation_catalog("S1", "S2", "S3", "S4"),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "Embedding 模型负责海选阶段（召回），快速从海量信息中捕获所有可能相关的候选项；其技术架构是双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动问题。",
                "citation_ids": ["S1", "S2"],
                "claims": [],
                "review_status": "passed",
            },
            {
                "paragraph_id": "p2",
                "text": "Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分；其技术架构是将查询与单个候选项整体输入模型，主要挑战是算力与性能的平衡。",
                "citation_ids": ["S3", "S4"],
                "claims": [],
                "review_status": "passed",
            },
        ],
        "stage_summaries": {},
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
    }

    async def _fake_judge_structured(**_: object) -> tuple[AnswerReviewSubDecision, None]:
        return (
            AnswerReviewSubDecision(
                passed=True,
                reason="passed",
                confidence=0.96,
                affected_paragraph_ids=[],
            ),
            None,
        )

    monkeypatch.setattr(answer_subgraph, "_judge_structured", _fake_judge_structured)

    updates = await answer_subgraph._answer_review(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=SimpleNamespace(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "incomplete"
    assert review_run["decision_source"] == "deterministic_guard"
    assert review_run["affected_paragraph_ids"] == ["p2"]
    assert review_run["details"]["coverage_guardrail"] == "required_original_terms"
    assert review_run["details"]["missing_terms"] == {
        "Re-rank 模型": ["Cross-Encoder"]
    }
    assert review_run["details"]["repair_target_count"] == 1


@pytest.mark.asyncio
async def test_answer_review_overrides_passed_when_required_responsibility_label_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
        "draft_answer": (
            "Embedding 模型的职责是将用户搜索词、商品标题、文本内容等转化为向量，以捕捉语义相似性；"
            "其技术架构是双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动问题。[S4]\n\n"
            "Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分；"
            "其技术架构是交叉编码器（Cross-Encoder），主要挑战是算力与性能的平衡。[S2]"
        ),
        "final_context": (
            "[S4] ## 2.  Embedding 模型：语义理解与高效召回的“猎人”\n"
            "- **核心任务：理解 (Understanding)**\n"
            "  - 它扮演“翻译家”的角色，将用户的搜索词、商品标题、文本内容等转化成向量。\n"
            "- **技术架构：双塔结构 (Dual-Encoder)**\n"
            "  - 一个塔编码查询，另一个塔编码物品。\n"
            "- **面临的挑战：向量表达的对齐与冷启动**\n"
            "  - 需要解决语义对齐与新物品冷启动问题。\n"
            "[S2] ## 3. Re-rank模型：深度匹配与精准排序的“裁判”\n"
            "- **核心任务：排序 (Ranking)**\n"
            "- **技术架构：交叉编码器 (Cross-Encoder)**\n"
            "- **面临的挑战：算力与性能的平衡**"
        ),
        "citation_catalog": _build_citation_catalog("S4", "S2"),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "Embedding 模型的职责是将用户搜索词、商品标题、文本内容等转化为向量，以捕捉语义相似性；其技术架构是双塔结构（Dual-Encoder），主要挑战是向量表达对齐与冷启动问题。",
                "citation_ids": ["S4"],
                "claims": [],
                "review_status": "passed",
            },
            {
                "paragraph_id": "p2",
                "text": "Re-rank 模型负责决赛阶段（排序），对候选项进行精细化打分；其技术架构是交叉编码器（Cross-Encoder），主要挑战是算力与性能的平衡。",
                "citation_ids": ["S2"],
                "claims": [],
                "review_status": "passed",
            },
        ],
        "stage_summaries": {},
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
    }

    async def _fake_judge_structured(**_: object) -> tuple[AnswerReviewSubDecision, None]:
        return (
            AnswerReviewSubDecision(
                passed=True,
                reason="passed",
                confidence=0.96,
                affected_paragraph_ids=[],
            ),
            None,
        )

    monkeypatch.setattr(answer_subgraph, "_judge_structured", _fake_judge_structured)

    updates = await answer_subgraph._answer_review(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=SimpleNamespace(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "incomplete"
    assert review_run["decision_source"] == "deterministic_guard"
    assert review_run["affected_paragraph_ids"] == ["p1"]
    assert review_run["details"]["coverage_guardrail"] == "required_original_terms"
    assert review_run["details"]["missing_terms"] == {"Embedding 模型": ["理解"]}
    assert review_run["details"]["repair_target_count"] == 1


class _ExplodingBindModel:
    def bind(self, **_: object) -> object:
        raise AssertionError("auxiliary_only deterministic prune 不应再调用 LLM repair")


class _StaticRepairRunnable:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, _: object) -> object:
        return SimpleNamespace(content=self._content)


class _StaticRepairModel:
    def __init__(self, content: str) -> None:
        self._content = content

    def bind(self, **_: object) -> _StaticRepairRunnable:
        return _StaticRepairRunnable(self._content)


@pytest.mark.asyncio
async def test_answer_repair_prunes_auxiliary_only_unsupported_paragraph_metadata() -> None:
    state = {
        **_build_state(),
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。它总能优于 Tree of Thoughts。[S1][S2]",
        "final_answer": "CoT 更适合单路径、步骤明确的推理任务。它总能优于 Tree of Thoughts。[S1][S2]",
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "CoT 更适合单路径、步骤明确的推理任务。它总能优于 Tree of Thoughts。",
                "citation_ids": ["S1", "S2"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 更适合单路径、步骤明确的推理任务。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S1"],
                    },
                    {
                        "claim_id": "c2",
                        "claim_text": "它总能优于 Tree of Thoughts。",
                        "role": "auxiliary",
                        "support_status": "unsupported",
                        "supporting_citation_ids": ["S2"],
                    },
                ],
                "review_status": "needs_repair",
            }
        ],
        "answer_render_meta": {
            "paragraph_count": 1,
            "claim_count": 2,
            "citation_count": 2,
            "citation_mode": "paragraph_aggregate",
        },
        "reflection": {
            "reason": "unsupported_claims",
            "review_breakdown": {
                "answer": {
                    "reason": "unsupported_claims",
                    "details": {
                        "unsupported_scope": "auxiliary_only",
                    },
                }
            },
        },
        "answer_subgraph_state": {
            "repair_attempts": 0,
        },
        "stage_summaries": {},
    }

    updates = await answer_subgraph._answer_repair(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=_ExplodingBindModel(),
    )

    assert updates["answer_paragraphs"] == [
        {
            "paragraph_id": "p1",
            "text": "CoT 更适合单路径、步骤明确的推理任务。",
            "citation_ids": ["S1"],
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "CoT 更适合单路径、步骤明确的推理任务。",
                    "role": "main",
                    "support_status": "supported",
                    "supporting_citation_ids": ["S1"],
                }
            ],
            "review_status": "passed",
        }
    ]
    assert updates["answer_render_meta"] == {
        "paragraph_count": 1,
        "claim_count": 1,
        "citation_count": 1,
        "citation_mode": "paragraph_aggregate",
    }
    assert updates["draft_answer"] == "CoT 更适合单路径、步骤明确的推理任务。[S1]"
    assert updates["final_answer"] == updates["draft_answer"]
    assert (
        updates["stage_summaries"]["answer_repair"]["fallback_reason"]
        == "deterministic_auxiliary_prune"
    )


@pytest.mark.asyncio
async def test_answer_repair_reprojects_paragraph_metadata_after_llm_citation_repair() -> None:
    state = {
        **_build_state(),
        "draft_answer": "旧回答没有正确引用。",
        "final_answer": "旧回答没有正确引用。",
        "answer_paragraphs": [
            {
                "paragraph_id": "p_old",
                "text": "旧回答没有正确引用。",
                "citation_ids": [],
                "claims": [],
                "review_status": "needs_repair",
            }
        ],
        "answer_render_meta": {
            "paragraph_count": 1,
            "claim_count": 0,
            "citation_count": 0,
            "citation_mode": "paragraph_aggregate",
        },
        "reflection": {
            "reason": "missing_citations",
            "review_breakdown": {
                "answer": {
                    "reason": "passed",
                    "details": {
                        "unsupported_scope": "none",
                    },
                }
            },
        },
        "answer_subgraph_state": {
            "repair_attempts": 0,
        },
        "stage_summaries": {},
    }

    updates = await answer_subgraph._answer_repair(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=_StaticRepairModel("修复后的第一段。[S1]\n\n修复后的第二段。[S2]"),
    )

    assert updates["draft_answer"] == "修复后的第一段。[S1]\n\n修复后的第二段。[S2]"
    assert updates["final_answer"] == updates["draft_answer"]
    assert updates["answer_paragraphs"] == [
        {
            "paragraph_id": "p1",
            "text": "修复后的第一段。",
            "citation_ids": ["S1"],
            "claims": [],
            "review_status": "passed",
        },
        {
            "paragraph_id": "p2",
            "text": "修复后的第二段。",
            "citation_ids": ["S2"],
            "claims": [],
            "review_status": "passed",
        },
    ]
    assert updates["answer_render_meta"] == {
        "paragraph_count": 2,
        "claim_count": 0,
        "citation_count": 2,
        "citation_mode": "paragraph_aggregate",
    }


@pytest.mark.asyncio
async def test_answer_repair_without_citations_still_fails_followup_citation_review() -> None:
    state = {
        **_build_state(),
        "draft_answer": "旧回答没有正确引用。",
        "final_answer": "旧回答没有正确引用。",
        "answer_paragraphs": [
            {
                "paragraph_id": "p_old",
                "text": "旧回答没有正确引用。",
                "citation_ids": [],
                "claims": [],
                "review_status": "needs_repair",
            }
        ],
        "answer_render_meta": {
            "paragraph_count": 1,
            "claim_count": 0,
            "citation_count": 0,
            "citation_mode": "paragraph_aggregate",
        },
        "reflection": {
            "reason": "missing_citations",
            "review_breakdown": {
                "answer": {
                    "reason": "passed",
                    "details": {
                        "unsupported_scope": "none",
                    },
                }
            },
        },
        "answer_subgraph_state": {
            "repair_attempts": 0,
        },
        "stage_summaries": {},
    }

    repaired_updates = await answer_subgraph._answer_repair(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=_StaticRepairModel("修复后的第一段。\n\n修复后的第二段。"),
    )

    assert repaired_updates["draft_answer"] == state["draft_answer"]
    assert repaired_updates["final_answer"] == state["final_answer"]
    assert "answer_paragraphs" not in repaired_updates
    assert "answer_render_meta" not in repaired_updates
    assert (
        repaired_updates["stage_summaries"]["answer_repair"]["fallback_reason"]
        == "repair_projection_missing_citations"
    )

    review_updates = await answer_subgraph._answer_review_citation(
        {
            **state,
            **repaired_updates,
        },
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )

    review_run = review_updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "missing_citations"
    assert review_run["affected_paragraph_ids"] == ["p_old"]
    assert review_run["details"]["paragraph_review_counts"] == {
        "total": 1,
        "passed": 0,
        "failed": 1,
    }


@pytest.mark.asyncio
async def test_paragraph_citation_review_fails_projected_text_without_citations_or_claims() -> None:
    state = {
        **_build_state(),
        "draft_answer": "这是修复后的回答，但依然没有任何引用。",
    }

    updates = await answer_subgraph._answer_review_citation(
        state,
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )

    review_run = updates["answer_review_runs"][0]
    assert review_run["passed"] is False
    assert review_run["reason"] == "missing_citations"
    assert review_run["affected_paragraph_ids"] == ["p1"]


@pytest.mark.asyncio
async def test_answer_repair_normalizes_fullwidth_citations_before_projection() -> None:
    state = {
        "user_input": "说明 Re-rank 模型的技术架构。",
        "draft_answer": "旧答案。",
        "final_context": (
            "[S1] Re-rank 模型负责排序。\n"
            "[S4] 常见技术架构是交叉编码器。"
        ),
        "citation_catalog": _build_citation_catalog("S1", "S4"),
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
    }

    updates = await answer_subgraph._answer_repair(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=_StaticRepairModel(
            "Re‑rank 模型负责排序，并常用交叉编码器做深度匹配。【S1】【S4】"
        ),
    )

    assert updates["draft_answer"] == "Re-rank 模型负责排序，并常用交叉编码器做深度匹配。[S1][S4]"
    assert updates["answer_paragraphs"][0]["citation_ids"] == ["S1", "S4"]
    assert updates["stage_summaries"]["answer_repair"]["fallback_reason"] is None
