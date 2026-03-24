from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic import answer_subgraph
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


class _ExplodingBindModel:
    def bind(self, **_: object) -> object:
        raise AssertionError("当前场景不应调用 LLM repair")


class _StaticRepairRunnable:
    def __init__(self, content: str) -> None:
        self._content = content
        self.requests: list[object] = []

    async def ainvoke(self, request: object) -> object:
        self.requests.append(request)
        return SimpleNamespace(content=self._content)


class _StaticRepairModel:
    def __init__(self, content: str) -> None:
        self._content = content
        self.runnable: _StaticRepairRunnable | None = None

    def bind(self, **_: object) -> _StaticRepairRunnable:
        self.runnable = _StaticRepairRunnable(self._content)
        return self.runnable


@pytest.mark.asyncio
async def test_answer_repair_removes_unsupported_auxiliary_claims_and_recalculates_citations() -> None:
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
    assert updates["stage_summaries"]["answer_repair"]["repair_mode"] == (
        "deterministic_auxiliary_prune"
    )
    assert updates["stage_summaries"]["answer_repair"]["fallback_reason"] == (
        "deterministic_auxiliary_prune"
    )
    assert updates["stage_summaries"]["answer_repair"]["removed_auxiliary_claim_count"] == 1
    assert updates["stage_summaries"]["answer_repair"]["rerendered_paragraph_count"] == 1
    assert updates["stage_summaries"]["answer_repair"]["claim_count"] == 1
    assert updates["stage_summaries"]["answer_repair"]["citation_count"] == 1


@pytest.mark.asyncio
async def test_answer_repair_does_not_auto_fix_unsupported_main_claim() -> None:
    original_answer = "CoT 一定优于所有树搜索策略。[S1]"
    state = {
        **_build_state(),
        "draft_answer": original_answer,
        "final_answer": original_answer,
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "CoT 一定优于所有树搜索策略。",
                "citation_ids": ["S1"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 一定优于所有树搜索策略。",
                        "role": "main",
                        "support_status": "unsupported",
                        "supporting_citation_ids": ["S1"],
                    }
                ],
                "review_status": "failed",
            }
        ],
        "answer_render_meta": {
            "paragraph_count": 1,
            "claim_count": 1,
            "citation_count": 1,
            "citation_mode": "paragraph_aggregate",
        },
        "reflection": {
            "reason": "unsupported_claims",
            "review_breakdown": {
                "answer": {
                    "reason": "unsupported_claims",
                    "details": {
                        "unsupported_scope": "main",
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

    assert updates["draft_answer"] == original_answer
    assert updates["final_answer"] == original_answer
    assert updates["stage_summaries"]["answer_repair"]["repair_mode"] == "scope_blocked"
    assert (
        updates["stage_summaries"]["answer_repair"]["fallback_reason"]
        == "repair_scope_not_supported"
    )


@pytest.mark.asyncio
async def test_answer_repair_rejects_llm_candidate_without_paragraph_citations() -> None:
    original_answer = "旧回答仍缺引用。"
    state = {
        **_build_state(),
        "draft_answer": original_answer,
        "final_answer": original_answer,
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "旧回答仍缺引用。",
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
        chat_model=_StaticRepairModel("修复后的第一段。\n\n修复后的第二段。"),
    )

    assert updates["draft_answer"] == original_answer
    assert updates["final_answer"] == original_answer
    assert "answer_paragraphs" not in updates
    assert "answer_render_meta" not in updates
    assert updates["stage_summaries"]["answer_repair"]["repair_mode"] == "llm_or_fallback"
    assert (
        updates["stage_summaries"]["answer_repair"]["fallback_reason"]
        == "repair_projection_missing_citations"
    )


@pytest.mark.asyncio
async def test_answer_repair_prompt_includes_multi_entity_coverage_checklist() -> None:
    model = _StaticRepairModel(
        "Embedding 模型负责海选阶段（召回），技术架构是双塔结构（Dual-Encoder），挑战是向量表达对齐与冷启动。[S1][S2]\n\n"
        "Re-rank 模型负责决赛阶段（排序），技术架构是交叉编码器（Cross-Encoder），挑战是算力与性能的平衡。[S3][S4]"
    )
    state = {
        "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
        "draft_answer": (
            "Embedding 模型负责海选阶段（召回），技术架构是双塔结构（Dual-Encoder），"
            "挑战是向量表达对齐与冷启动。[S1][S2]\n\n"
            "关于 Re-rank 模型，参考内容未提供相应信息。"
        ),
        "final_answer": (
            "Embedding 模型负责海选阶段（召回），技术架构是双塔结构（Dual-Encoder），"
            "挑战是向量表达对齐与冷启动。[S1][S2]\n\n"
            "关于 Re-rank 模型，参考内容未提供相应信息。"
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
                "text": "Embedding 模型负责海选阶段（召回），技术架构是双塔结构（Dual-Encoder），挑战是向量表达对齐与冷启动。",
                "citation_ids": ["S1", "S2"],
                "claims": [],
                "review_status": "passed",
            },
            {
                "paragraph_id": "p2",
                "text": "关于 Re-rank 模型，参考内容未提供相应信息。",
                "citation_ids": [],
                "claims": [],
                "review_status": "needs_repair",
            },
        ],
        "answer_render_meta": {
            "paragraph_count": 2,
            "claim_count": 0,
            "citation_count": 2,
            "citation_mode": "paragraph_aggregate",
        },
        "reflection": {
            "reason": "missing_citations",
            "review_breakdown": {
                "answer": {
                    "reason": "incomplete",
                    "details": {
                        "unsupported_scope": "none",
                    },
                }
            },
        },
        "answer_subgraph_state": {
            "repair_attempts": 0,
        },
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
    }

    await answer_subgraph._answer_repair(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=model,
    )

    assert model.runnable is not None
    request = model.runnable.requests[0]
    prompt = request[1].content
    assert "覆盖清单：" in prompt
    assert "- Embedding 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：召回 / Dual-Encoder" in prompt
    assert "- Re-rank 模型: 职责 / 技术架构 / 挑战；必须保留原始名词：排序 / Cross-Encoder" in prompt
    assert "不得把整实体写成“资料不足”" in prompt
