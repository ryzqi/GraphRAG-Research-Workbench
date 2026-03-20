from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.schemas import RetrievalPlanDecision
from app.services.query_rewrite_service import (
    QueryRewriteService,
    StructuredCallResult,
)


@pytest.mark.asyncio
async def test_plan_retrieval_budget_uses_structured_prompt_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QueryRewriteService(settings=SimpleNamespace())

    monkeypatch.setattr(service, "_get_structured_agent", lambda schema: object())

    async def _fake_invoke_structured(
        *,
        agent: object,
        schema: type[RetrievalPlanDecision],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        del agent, schema, max_tokens
        assert "输出要求" in user_prompt
        return StructuredCallResult(
            payload=RetrievalPlanDecision(
                per_query_top_k=6,
                global_candidates_limit=24,
                rerank_input_limit=12,
                reasoning="simple_budget",
            ),
            success=True,
            reason=None,
        )

    monkeypatch.setattr(service, "_invoke_structured", _fake_invoke_structured)

    result = await service.plan_retrieval_budget(
        question="系统默认超时时间是多少",
        normalized_query="系统默认超时时间是多少",
        complexity_level="simple",
        query_items=[{"kind": "main", "query": "系统默认超时时间是多少"}],
        retry_count=0,
        failure_reason="",
        max_top_k=10,
        fallback_budget={
            "per_query_top_k": 5,
            "global_candidates_limit": 20,
            "rerank_input_limit": 10,
        },
    )

    assert result.success is True
    assert result.reason is None
    assert result.budget == {
        "per_query_top_k": 6,
        "global_candidates_limit": 24,
        "rerank_input_limit": 12,
    }
    assert isinstance(result.meta, dict)
    assert result.meta["fallback_used"] is False
    assert result.meta["reasoning"] == "simple_budget"
