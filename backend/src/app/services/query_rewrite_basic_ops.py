from __future__ import annotations

import asyncio
import logging
import time

from app.agents.kb_chat_agentic.schemas import NormalizeDecision, ReferenceResolutionDecision
from app.services.query_rewrite_contracts import RewriteResult
from app.services.query_rewrite_text import (
    _default_clarification_question,
    _normalize_guardrail_reason,
    _normalize_whitespace,
    _render_recent_turns,
    _sanitize_aliases,
    _sanitize_query_text,
)

logger = logging.getLogger(__name__)
async def rewrite(
    service,
    query: str,
    *,
    max_tokens: int | None = None,
    prompt_key: str = "retrieval/query_rewrite",
) -> RewriteResult:
    if not query.strip():
        return RewriteResult(query=query, rewritten=False, reason="empty")

    try:
        prompt = service._prompts.render_with_few_shot(prompt_key, question=query)
    except KeyError:
        return RewriteResult(query=query, rewritten=False, reason="prompt_missing")
    start_time = time.perf_counter()

    max_tokens_value = (
        int(service._settings.retrieval_query_rewrite_max_tokens)
        if max_tokens is None
        else int(max_tokens)
    )
    try:
        rewritten = await service._call_llm(prompt, max_tokens=max_tokens_value)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.warning("Query rewrite 调用失败", extra={"error": str(exc)})
        return RewriteResult(
            query=query,
            rewritten=False,
            reason="error",
            latency_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    rewritten = _sanitize_query_text((rewritten or "").strip())
    if not rewritten:
        return RewriteResult(
            query=query,
            rewritten=False,
            reason="empty_output",
            latency_ms=latency_ms,
        )

    return RewriteResult(
        query=rewritten,
        rewritten=rewritten != query,
        reason=None,
        latency_ms=latency_ms,
    )

async def resolve_reference(
    service,
    query: str,
    *,
    enabled: bool = True,
    recent_turns: list[dict[str, str]] | None = None,
    summary_text: str | None = None,
    memory_snippet: str | None = None,
) -> RewriteResult:
    """使用 LLM 解析对话指代；失败时回退到原始查询。"""
    start = time.perf_counter()
    q = _sanitize_query_text(query)
    if not enabled:
        return RewriteResult(
            query=q,
            rewritten=False,
            reason="disabled",
            latency_ms=0,
            meta={
                "triggered": False,
                "confidence": 0.0,
                "selected_mention": "",
                "resolution_source": "disabled",
                "reasoning": "",
                "needs_clarification": False,
            },
        )
    if not q:
        return RewriteResult(
            query=q,
            rewritten=False,
            reason="empty",
            latency_ms=0,
            meta={
                "triggered": False,
                "confidence": 0.0,
                "selected_mention": "",
                "resolution_source": "empty",
                "reasoning": "",
                "needs_clarification": False,
            },
        )
    structured_result = await service._call_prompt_structured(
        "kb_chat/resolve_reference",
        schema=ReferenceResolutionDecision,
        max_tokens=320,
        question=q,
        recent_turns=_render_recent_turns(recent_turns),
        summary_text=_normalize_whitespace(summary_text or ""),
        memory_snippet=_normalize_whitespace(memory_snippet or ""),
    )
    if structured_result.success and isinstance(
        structured_result.payload, ReferenceResolutionDecision
    ):
        payload = structured_result.payload
        resolved_query = _sanitize_query_text(payload.resolved_query) or q
        confidence = round(max(0.0, min(1.0, float(payload.confidence))), 4)
        needs_clarification = bool(payload.needs_clarification)
        reasoning = _normalize_whitespace(payload.reasoning or "")
        selected_mention = _normalize_whitespace(payload.selected_mention or "")
        triggered = bool(
            payload.triggered or resolved_query != q or selected_mention
        )
        return RewriteResult(
            query=resolved_query,
            rewritten=resolved_query != q,
            reason="llm_structured",
            latency_ms=int((time.perf_counter() - start) * 1000),
            meta={
                "triggered": triggered,
                "confidence": confidence,
                "selected_mention": selected_mention,
                "resolution_source": "llm_structured",
                "reasoning": reasoning,
                "needs_clarification": needs_clarification,
                "clarification_hint": (
                    _default_clarification_question() if needs_clarification else ""
                ),
            },
        )

    fallback_reason = structured_result.reason or "llm_unavailable"
    return RewriteResult(
        query=q,
        rewritten=False,
        reason=fallback_reason,
        latency_ms=int((time.perf_counter() - start) * 1000),
        meta={
            "triggered": False,
            "confidence": 0.0,
            "selected_mention": "",
            "resolution_source": "fail_open",
            "reasoning": "",
            "needs_clarification": False,
            "fallback_reason": fallback_reason,
        },
    )

async def coref_rewrite(
    service,
    query: str,
    *,
    enabled: bool = True,
    recent_turns: list[dict[str, str]] | None = None,
    summary_text: str | None = None,
    memory_snippet: str | None = None,
) -> RewriteResult:
    """面向 LLM 指代消解的向后兼容别名。"""
    return await service.resolve_reference(
        query,
        enabled=enabled,
        recent_turns=recent_turns,
        summary_text=summary_text,
        memory_snippet=memory_snippet,
    )

async def normalize_rewrite(
    service,
    query: str,
) -> RewriteResult:
    """仅使用结构化 LLM 输出规范化查询；失败时回退到原始查询。"""
    start = time.perf_counter()
    q = _sanitize_query_text(query)
    if not q:
        return RewriteResult(query=q, rewritten=False, reason="empty", latency_ms=0)

    structured_result = await service._call_prompt_structured(
        "kb_chat/normalize_query",
        schema=NormalizeDecision,
        max_tokens=320,
        question=q,
    )
    fallback_reason = structured_result.reason or "llm_failed_fail_open"
    if structured_result.success and isinstance(
        structured_result.payload, NormalizeDecision
    ):
        payload = structured_result.payload
        candidate_query = _sanitize_query_text(payload.canonical_query)
        if (
            candidate_query
            and bool(payload.constraint_preserved)
            and not bool(payload.drift_risk)
        ):
            recall_risk = payload.recall_risk
            if recall_risk not in {"low", "medium", "high"}:
                recall_risk = "medium"
            latency_ms = int((time.perf_counter() - start) * 1000)
            guardrail_reason = _normalize_guardrail_reason(q, candidate_query)
            payload_meta = {
                "aliases": _sanitize_aliases(payload.aliases, limit=8),
                "entities": _sanitize_aliases(payload.entities, limit=8),
                "time_constraints": _sanitize_aliases(
                    payload.time_constraints,
                    limit=6,
                ),
                "metric_constraints": _sanitize_aliases(
                    payload.metric_constraints,
                    limit=6,
                ),
                "scope_constraints": _sanitize_aliases(
                    payload.scope_constraints,
                    limit=6,
                ),
                "recall_risk": recall_risk,
                "drift_risk": bool(payload.drift_risk),
                "constraint_preserved": bool(payload.constraint_preserved),
                "has_multi_target": bool(payload.has_multi_target),
                "is_comparison": bool(payload.is_comparison),
                "reasoning": _normalize_whitespace(payload.reasoning or ""),
            }
            if guardrail_reason is not None:
                return RewriteResult(
                    query=q,
                    rewritten=False,
                    reason="guardrail_preserve_original",
                    latency_ms=latency_ms,
                    meta={
                        **payload_meta,
                        "source": "guardrail_preserve_original",
                        "fallback_reason": guardrail_reason,
                        "guardrail_reason": guardrail_reason,
                    },
                )
            return RewriteResult(
                query=candidate_query,
                rewritten=candidate_query != q,
                reason="llm_structured",
                latency_ms=latency_ms,
                meta={
                    "source": "llm_structured",
                    "fallback_reason": "",
                    **payload_meta,
                },
            )
        if not candidate_query:
            fallback_reason = "empty_output"
        elif bool(payload.drift_risk):
            fallback_reason = "drift_risk_fail_open"
        else:
            fallback_reason = "constraint_not_preserved"

    latency_ms = int((time.perf_counter() - start) * 1000)
    return RewriteResult(
        query=q,
        rewritten=False,
        reason=fallback_reason,
        latency_ms=latency_ms,
        meta={
            "source": "fail_open",
            "fallback_reason": fallback_reason,
            "aliases": [],
            "entities": [],
            "time_constraints": [],
            "metric_constraints": [],
            "scope_constraints": [],
            "recall_risk": "medium",
            "drift_risk": False,
            "constraint_preserved": True,
            "has_multi_target": False,
            "is_comparison": False,
            "reasoning": "",
        },
    )

