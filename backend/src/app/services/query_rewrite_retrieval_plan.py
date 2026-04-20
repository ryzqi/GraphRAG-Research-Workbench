from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from app.agents.kb_chat_agentic.schemas import RetrievalPlanDecision
from app.services.query_rewrite_contracts import RetrievalPlanResult
from app.services.query_rewrite_text import (
    _normalize_whitespace,
    _render_query_items,
)


async def plan_retrieval_budget(
    service,
    *,
    question: str,
    normalized_query: str,
    complexity_level: str,
    query_items: Sequence[Mapping[str, object]] | None,
    retry_count: int,
    failure_reason: str,
    max_top_k: int,
    fallback_budget: dict[str, int],
) -> RetrievalPlanResult:
    """使用 LLM 规划检索预算；失败时回退到给定的兜底预算。"""
    start = time.perf_counter()
    normalized_items = list(query_items) if query_items is not None else []
    query_count = max(
        1,
        sum(
            1
            for item in normalized_items
            if isinstance(item, dict)
            and _normalize_whitespace(str(item.get("query") or ""))
        ),
    )
    structured_result = await service._call_prompt_structured(
        "kb_chat/retrieval_plan",
        schema=RetrievalPlanDecision,
        max_tokens=240,
        question=_normalize_whitespace(question),
        normalized_query=_normalize_whitespace(normalized_query),
        complexity_level=_normalize_whitespace(complexity_level) or "simple",
        query_count=query_count,
        query_items="\n".join(_render_query_items(normalized_items) or [])
        or "1. [main] 无",
        retry_count=max(0, int(retry_count)),
        failure_reason=_normalize_whitespace(failure_reason) or "none",
        fallback_per_query_top_k=max(
            1, int(fallback_budget.get("per_query_top_k") or 1)
        ),
        fallback_global_candidates_limit=max(
            1, int(fallback_budget.get("global_candidates_limit") or 1)
        ),
        fallback_rerank_input_limit=max(
            1, int(fallback_budget.get("rerank_input_limit") or 1)
        ),
        fallback_final_evidence_token_budget=max(
            1, int(fallback_budget.get("final_evidence_token_budget") or 1)
        ),
        max_top_k=max(1, int(max_top_k)),
    )

    fallback_reason = structured_result.reason or ""
    planning_reasoning = ""
    budget = {
        "per_query_top_k": max(1, int(fallback_budget.get("per_query_top_k") or 1)),
        "global_candidates_limit": max(
            1, int(fallback_budget.get("global_candidates_limit") or 1)
        ),
        "rerank_input_limit": max(
            1, int(fallback_budget.get("rerank_input_limit") or 1)
        ),
        "final_evidence_token_budget": max(
            1, int(fallback_budget.get("final_evidence_token_budget") or 1)
        ),
    }

    if structured_result.success and isinstance(
        structured_result.payload, RetrievalPlanDecision
    ):
        payload = structured_result.payload
        safe_max_top_k = max(1, int(max_top_k))
        safe_final_evidence_token_budget = max(
            1, int(fallback_budget.get("final_evidence_token_budget") or 1)
        )
        per_query_top_k = max(1, min(int(payload.per_query_top_k), safe_max_top_k))
        max_global_candidates = max(safe_max_top_k * 6, per_query_top_k)
        rerank_input_limit = max(
            per_query_top_k,
            min(
                int(payload.rerank_input_limit),
                max(max_global_candidates, safe_max_top_k * 4),
            ),
        )
        global_candidates_limit = max(
            rerank_input_limit,
            min(int(payload.global_candidates_limit), max_global_candidates),
        )
        final_evidence_token_budget = max(
            1,
            min(int(payload.final_evidence_token_budget), safe_final_evidence_token_budget),
        )
        budget = {
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
            "final_evidence_token_budget": final_evidence_token_budget,
        }
        planning_reasoning = _normalize_whitespace(payload.reasoning or "")
        fallback_reason = ""

    latency_ms = int((time.perf_counter() - start) * 1000)
    return RetrievalPlanResult(
        budget=budget,
        success=bool(
            structured_result.success and structured_result.payload is not None
        ),
        reason=fallback_reason or None,
        latency_ms=latency_ms,
        meta={
            "decision_source": "llm",
            "fallback_reason": fallback_reason,
            "fallback_used": bool(fallback_reason),
            "reasoning": planning_reasoning,
            "query_count": query_count,
        },
    )
