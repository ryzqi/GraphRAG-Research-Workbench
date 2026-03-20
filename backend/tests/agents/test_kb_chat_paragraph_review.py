from __future__ import annotations

from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_paragraph_citation_review_passes_when_main_claim_matches_aggregate_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def _legacy_coverage_should_not_run(_: str) -> object:
        raise AssertionError("answer_review_citation 不应再调用 review_citation_coverage")

    monkeypatch.setattr(
        answer_subgraph,
        "review_citation_coverage",
        _legacy_coverage_should_not_run,
    )

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
async def test_answer_review_fuse_routes_auxiliary_only_unsupported_to_repair() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 1,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。[S1]",
        "stage_summaries": {},
        "answer_review_runs": [
            {
                "review_round": 0,
                "check": "citation",
                "passed": True,
                "reason": "passed",
                "confidence": 1.0,
                "details": {
                    "paragraph_review_counts": {"total": 1, "passed": 1, "failed": 0},
                    "repair_target_count": 0,
                    "unsupported_scope": "none",
                },
                "affected_paragraph_ids": [],
            },
            {
                "review_round": 0,
                "check": "answer",
                "passed": False,
                "reason": "unsupported_claims",
                "confidence": 0.92,
                "details": {
                    "paragraph_review_counts": {"total": 1, "passed": 0, "failed": 1},
                    "repair_target_count": 1,
                    "unsupported_scope": "auxiliary_only",
                },
                "affected_paragraph_ids": ["p1"],
            },
        ],
    }

    command = await answer_subgraph._answer_review_fuse(
        state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert command.goto == "answer_repair"
    assert command.update["stage_summaries"]["answer_review"]["repair_target_count"] == 1
    assert (
        command.update["stage_summaries"]["answer_review"]["unsupported_scope_summary"]
        == "auxiliary_only"
    )


@pytest.mark.asyncio
async def test_answer_review_fuse_does_not_route_main_unsupported_to_repair() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 1,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。[S1]",
        "stage_summaries": {},
        "answer_review_runs": [
            {
                "review_round": 0,
                "check": "citation",
                "passed": True,
                "reason": "passed",
                "confidence": 1.0,
                "details": {
                    "paragraph_review_counts": {"total": 1, "passed": 1, "failed": 0},
                    "repair_target_count": 0,
                    "unsupported_scope": "none",
                },
                "affected_paragraph_ids": [],
            },
            {
                "review_round": 0,
                "check": "answer",
                "passed": False,
                "reason": "unsupported_claims",
                "confidence": 0.92,
                "details": {
                    "paragraph_review_counts": {"total": 1, "passed": 0, "failed": 1},
                    "repair_target_count": 1,
                    "unsupported_scope": "main",
                },
                "affected_paragraph_ids": ["p1"],
            },
        ],
    }

    command = await answer_subgraph._answer_review_fuse(
        state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert command.goto == "answer_commit"


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
async def test_answer_repair_reprojects_paragraph_metadata_after_llm_citation_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        answer_subgraph,
        "_citation_coverage_score",
        lambda answer: (10, 2, 2) if answer.startswith("修复后") else (0, 0, 0),
    )

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
async def test_answer_repair_without_citations_still_fails_followup_citation_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        answer_subgraph,
        "_citation_coverage_score",
        lambda _: (0, 0, 0),
    )

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

    assert repaired_updates["answer_paragraphs"] == [
        {
            "paragraph_id": "p1",
            "text": "修复后的第一段。",
            "citation_ids": [],
            "claims": [],
            "review_status": "passed",
        },
        {
            "paragraph_id": "p2",
            "text": "修复后的第二段。",
            "citation_ids": [],
            "claims": [],
            "review_status": "passed",
        },
    ]

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
    assert review_run["affected_paragraph_ids"] == ["p1", "p2"]
    assert review_run["details"]["paragraph_review_counts"] == {
        "total": 2,
        "passed": 0,
        "failed": 2,
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
