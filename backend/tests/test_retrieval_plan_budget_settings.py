from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.dispatch_fuse import make_send_task
from app.agents.kb_chat_agentic.schemas import RetrievalPlanDecision
from app.agents.retrieval_subgraph import (
    _fallback_retrieval_budget,
    _merge_retrieval_plan_summary,
)
from app.core.settings import Settings
from app.services.query_rewrite_retrieval_plan import plan_retrieval_budget


class _StubQueryRewriteService:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def _call_prompt_structured(self, prompt_key: str, **kwargs):
        self.calls.append({"prompt_key": prompt_key, **kwargs})
        return self.result


def test_retrieval_plan_settings_defaults_include_final_evidence_token_budget() -> None:
    fields = Settings.model_fields

    assert fields["context_retrieval_max_tokens"].default == 16_000
    assert int(fields["context_retrieval_max_tokens"].default * 0.9) == 14_400


def test_fallback_retrieval_budget_adds_final_evidence_token_budget() -> None:
    budget, diagnostics = _fallback_retrieval_budget(
        {
            "complexity_level": "moderate",
            "query_items": [{"query": "问题"}],
            "loop_counts": {"retrieval_retries": 0},
        },
        Settings(CONTEXT_RETRIEVAL_MAX_TOKENS=16_000),
    )

    assert budget == {
        "per_query_top_k": 10,
        "global_candidates_limit": 50,
        "rerank_input_limit": 20,
        "final_evidence_token_budget": 14_400,
    }
    assert diagnostics["complexity"] == "moderate"
    assert diagnostics["query_count"] == 1


def test_retrieval_plan_schema_accepts_final_evidence_token_budget() -> None:
    decision = RetrievalPlanDecision.model_validate(
        {
            "per_query_top_k": 12,
            "global_candidates_limit": 60,
            "rerank_input_limit": 28,
            "final_evidence_token_budget": 12_800,
            "reasoning": "保持证据 token 预算低于最终上下文硬顶。",
        }
    )

    assert decision.final_evidence_token_budget == 12_800


@pytest.mark.asyncio
async def test_plan_retrieval_budget_passes_and_clamps_final_evidence_token_budget() -> None:
    structured_result = SimpleNamespace(
        success=True,
        payload=RetrievalPlanDecision.model_validate(
            {
                "per_query_top_k": 12,
                "global_candidates_limit": 60,
                "rerank_input_limit": 28,
                "final_evidence_token_budget": 99_999,
                "reasoning": "复杂问题提升召回，但证据 token 预算仍需受控。",
            }
        ),
        reason=None,
    )
    service = _StubQueryRewriteService(structured_result)

    result = await plan_retrieval_budget(
        service,
        question="比较 A 和 B 的差异",
        normalized_query="比较 A 和 B 的差异",
        complexity_level="complex",
        query_items=[{"query": "比较 A 和 B 的差异", "kind": "main"}],
        retry_count=1,
        failure_reason="retry",
        max_top_k=15,
        fallback_budget={
            "per_query_top_k": 12,
            "global_candidates_limit": 60,
            "rerank_input_limit": 28,
            "final_evidence_token_budget": 14_400,
        },
    )

    assert result.budget == {
        "per_query_top_k": 12,
        "global_candidates_limit": 60,
        "rerank_input_limit": 28,
        "final_evidence_token_budget": 14_400,
    }
    assert result.meta["query_count"] == 1
    assert service.calls[0]["fallback_final_evidence_token_budget"] == 14_400


def test_retrieval_plan_summary_carries_final_evidence_token_budget() -> None:
    stage_summaries = _merge_retrieval_plan_summary(
        {"stage_summaries": {}},
        budget={
            "per_query_top_k": 10,
            "global_candidates_limit": 50,
            "rerank_input_limit": 20,
            "final_evidence_token_budget": 14_400,
        },
        diagnostics={"complexity": "moderate", "query_count": 2},
        fallback_reason=None,
        fallback_used=False,
        reasoning="保持 moderate 档默认预算。",
        latency_ms=12,
    )

    assert (
        stage_summaries["retrieval_plan"]["final_evidence_token_budget"] == 14_400
    )


def test_make_send_task_preserves_final_evidence_token_budget_on_branch_state() -> None:
    send = make_send_task(
        "retrieve_subquery",
        {"subquery_task": {"query": "问题"}},
        {
            "loop_counts": {"retrieval_retries": 1},
            "retrieval_budget": {
                "per_query_top_k": 10,
                "global_candidates_limit": 50,
                "rerank_input_limit": 20,
                "final_evidence_token_budget": 14_400,
            },
        },
    )

    assert send.arg["retrieval_budget"]["final_evidence_token_budget"] == 14_400
