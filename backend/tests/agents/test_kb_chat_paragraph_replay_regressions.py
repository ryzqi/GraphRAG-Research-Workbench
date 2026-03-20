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
        "user_input": "请比较 CoT 和 ToT。",
        "final_context": (
            "[S1] CoT 适合单路径、逻辑明确的推理任务，计算开销较低。\n"
            "[S2] ToT 适合多方案探索与回溯，但通常需要更高的计算成本。"
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
        raise AssertionError("auxiliary_only deterministic prune 不应再调用 LLM repair")


@pytest.mark.asyncio
async def test_replay_paragraph_end_aggregate_citations_pass_without_per_sentence_markers() -> None:
    state = {
        **_build_state(),
        "draft_answer": (
            "CoT 通常适合单路径、逻辑明确的任务，而 ToT 更适合多方案探索与回溯，"
            "因此计算开销也更高。[S1][S2]"
        ),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": (
                    "CoT 通常适合单路径、逻辑明确的任务，而 ToT 更适合多方案探索与回溯，"
                    "因此计算开销也更高。"
                ),
                "citation_ids": ["S1", "S2"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 通常适合单路径、逻辑明确的任务。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S1"],
                    },
                    {
                        "claim_id": "c2",
                        "claim_text": "ToT 更适合多方案探索与回溯，因此计算开销也更高。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S2"],
                    },
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
    assert review_run["missing_citations"] == []
    assert review_run["affected_paragraph_ids"] == []
    assert review_run["details"]["paragraph_review_counts"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_replay_repair_prunes_unsupported_auxiliary_clause_and_followup_review_passes() -> None:
    state = {
        **_build_state(),
        "draft_answer": (
            "CoT 适合单路径、步骤明确的推理任务，因此在所有场景都比 ToT 更优。[S1][S2]"
        ),
        "final_answer": (
            "CoT 适合单路径、步骤明确的推理任务，因此在所有场景都比 ToT 更优。[S1][S2]"
        ),
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "CoT 适合单路径、步骤明确的推理任务，因此在所有场景都比 ToT 更优。",
                "citation_ids": ["S1", "S2"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 适合单路径、步骤明确的推理任务。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S1"],
                    },
                    {
                        "claim_id": "c2",
                        "claim_text": "在所有场景都比 ToT 更优。",
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
    }

    repaired_updates = await answer_subgraph._answer_repair(
        state,
        SimpleNamespace(),
        settings=Settings(),
        chat_model=_ExplodingBindModel(),
    )

    assert repaired_updates["draft_answer"] == "CoT 适合单路径、步骤明确的推理任务。[S1]"
    assert repaired_updates["final_answer"] == repaired_updates["draft_answer"]
    assert repaired_updates["answer_paragraphs"] == [
        {
            "paragraph_id": "p1",
            "text": "CoT 适合单路径、步骤明确的推理任务。",
            "citation_ids": ["S1"],
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "CoT 适合单路径、步骤明确的推理任务。",
                    "role": "main",
                    "support_status": "supported",
                    "supporting_citation_ids": ["S1"],
                }
            ],
            "review_status": "passed",
        }
    ]
    assert (
        repaired_updates["stage_summaries"]["answer_repair"]["fallback_reason"]
        == "deterministic_auxiliary_prune"
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
    assert review_run["passed"] is True
    assert review_run["reason"] == "passed"
    assert review_run["affected_paragraph_ids"] == []
