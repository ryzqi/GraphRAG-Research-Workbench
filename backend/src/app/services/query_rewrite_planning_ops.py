from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence

from app.agents.kb_chat_agentic.schemas import (
    COMPLEXITY_CLASSIFY_DECISION_VERSION,
    AmbiguityDecision,
    ComplexityDecision,
    DecompositionDecision,
    HyDEBatchDecision,
    MergeContextResolutionDecision,
    MultiQueryDecision,
    RetrievalPlanDecision,
    TransformQueryDecision,
)
from app.services.query_rewrite_contracts import (
    AmbiguityResult,
    ComplexityRouteResult,
    MergeContextResolutionResult,
    QueryListResult,
    RetrievalPlanResult,
    RewriteResult,
    StructuredCallResult,
)
from app.services.query_rewrite_items import (
    _coerce_fixed_multi_query_variants,
    _normalize_hyde_documents,
    _rule_based_decomposition_candidates,
)
from app.services.query_rewrite_text import (
    _build_clarification_payload,
    _decomposition_max_sub_queries,
    _default_clarification_question,
    _default_complexity_reason,
    _dedupe_keep_order,
    _hyde_num_hypotheses,
    _looks_compare_or_multi_target,
    _normalize_guardrail_reason,
    _normalize_reason_code,
    _normalize_whitespace,
    _render_query_items,
    _sanitize_query_text,
    _sanitize_reverse_question,
    _sanitize_risk_flags,
)

logger = logging.getLogger(__name__)
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
    }

    if structured_result.success and isinstance(
        structured_result.payload, RetrievalPlanDecision
    ):
        payload = structured_result.payload
        safe_max_top_k = max(1, int(max_top_k))
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
        budget = {
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
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

async def ambiguity_check(
    service,
    query: str,
    *,
    enabled: bool | None = None,
    coref_meta: dict[str, object] | None = None,
) -> AmbiguityResult:
    """模型驱动的歧义判定，并带护栏兜底。"""
    start = time.perf_counter()
    enabled_flag = True if enabled is None else bool(enabled)
    if not enabled_flag:
        disabled_reason = "当前未启用歧义澄清，继续后续检索。"
        return AmbiguityResult(
            ambiguous=False,
            reason=disabled_reason,
            latency_ms=0,
            model_reason=disabled_reason,
        )

    q = _sanitize_query_text(query)
    if not q:
        business_reason = "问题内容为空，需先补充具体问题。"
        payload = _build_clarification_payload(
            question=_default_clarification_question(),
            reason_code="missing_entity",
            confidence=1.0,
            model_reason=business_reason,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return AmbiguityResult(
            ambiguous=True,
            reverse_question=str(payload["question"]),
            reason=business_reason,
            latency_ms=latency_ms,
            reason_code="missing_entity",
            confidence=1.0,
            model_reason=business_reason,
            fallback_used=True,
            clarification_payload=payload,
        )

    coref_confidence = 0.0
    coref_hint = ""
    coref_selected_mention = ""
    coref_needs_clarification = False
    if isinstance(coref_meta, dict):
        confidence_value = coref_meta.get("confidence")
        if isinstance(confidence_value, (int, float)):
            coref_confidence = float(confidence_value)
        hint_value = coref_meta.get("clarification_hint")
        if isinstance(hint_value, str):
            coref_hint = _normalize_whitespace(hint_value)
        mention_value = coref_meta.get("selected_mention")
        if isinstance(mention_value, str):
            coref_selected_mention = _normalize_whitespace(mention_value)
        coref_needs_clarification = bool(coref_meta.get("needs_clarification"))

    try:
        prompt = service._prompts.render_with_few_shot(
            "kb_chat/ambiguity_decision",
            question=q,
            coref_confidence=round(max(0.0, min(1.0, coref_confidence)), 4),
            coref_hint=coref_hint,
            coref_selected_mention=coref_selected_mention,
            coref_needs_clarification=coref_needs_clarification,
        )
    except KeyError:
        structured_result = StructuredCallResult(
            payload=None,
            success=False,
            reason="prompt_missing",
            latency_ms=0,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Prompt render 失败",
            extra={"prompt_key": "kb_chat/ambiguity_decision", "error": str(exc)},
        )
        structured_result = StructuredCallResult(
            payload=None,
            success=False,
            reason="prompt_error",
            latency_ms=0,
        )
    else:
        structured_result = await service._invoke_model_structured(
            schema=AmbiguityDecision,
            user_prompt=prompt,
            max_tokens=320,
        )

    fallback_used = False
    ambiguous = False
    reason: str | None = None
    failure_reason: str | None = None
    reason_code = "mixed"
    confidence = 0.0
    model_reason = ""
    reverse_question: str | None = None
    clarification_payload: dict[str, object] | None = None

    if structured_result.success and isinstance(
        structured_result.payload, AmbiguityDecision
    ):
        payload = structured_result.payload
        ambiguous = bool(payload.ambiguous)
        reason_code = _normalize_reason_code(payload.reason_code)
        confidence = round(max(0.0, min(1.0, float(payload.confidence))), 4)
        model_reason = service._resolve_ambiguity_business_reason(
            ambiguous=ambiguous,
            model_reason=payload.reasoning,
            reason_code=reason_code,
        )
        reason = model_reason
        if ambiguous:
            question_text = _sanitize_reverse_question(
                payload.clarifying_question or ""
            )
            if not question_text:
                question_text = _default_clarification_question()
            clarification_payload = _build_clarification_payload(
                question=question_text,
                reason_code=reason_code,
                confidence=confidence,
                model_reason=model_reason,
                slots=payload.missing_slots,
                suggested_answers=payload.suggested_answers,
            )
            reverse_question = str(clarification_payload.get("question") or "")
    else:
        fallback_used = True
        ambiguous = service._is_ambiguous_heuristic(q)
        failure_reason = (
            structured_result.reason or "model_failed_guardrail_fallback"
        )
        if ambiguous:
            reason_code = (
                "coref_uncertain" if coref_needs_clarification else "mixed"
            )
            confidence = 0.35
            model_reason = service._resolve_ambiguity_business_reason(
                ambiguous=True,
                model_reason=None,
                reason_code=reason_code,
            )
            reason = model_reason
            clarification_payload = _build_clarification_payload(
                question=_default_clarification_question(),
                reason_code=reason_code,
                confidence=confidence,
                model_reason=model_reason,
            )
            reverse_question = str(clarification_payload.get("question") or "")
        else:
            model_reason = service._resolve_ambiguity_business_reason(
                ambiguous=False,
                model_reason=None,
                reason_code=None,
            )
            reason = model_reason

    latency_ms = int((time.perf_counter() - start) * 1000)
    return AmbiguityResult(
        ambiguous=ambiguous,
        reverse_question=reverse_question,
        reason=reason,
        failure_reason=failure_reason,
        latency_ms=latency_ms,
        reason_code=reason_code if ambiguous else None,
        confidence=confidence if ambiguous else None,
        model_reason=model_reason or None,
        fallback_used=fallback_used,
        clarification_payload=clarification_payload if ambiguous else None,
    )

async def transform_query(
    service,
    query: str,
    *,
    reason: str,
    hint: str | None = None,
    enabled: bool = True,
) -> RewriteResult:
    """为重试场景改写 / 扩展查询，并提供安全兜底。"""
    if not enabled:
        return RewriteResult(
            query=query,
            rewritten=False,
            reason="disabled",
            latency_ms=0,
        )

    structured_result = await service._call_prompt_structured(
        "kb_chat/transform_query",
        schema=TransformQueryDecision,
        max_tokens=96,
        question=query,
        reason=reason,
        hint=hint or "",
    )
    if (
        structured_result.success
        and isinstance(structured_result.payload, TransformQueryDecision)
        and structured_result.payload.query.strip()
    ):
        text = _sanitize_query_text(structured_result.payload.query.strip())
        guardrail_reason = _normalize_guardrail_reason(query, text)
        if guardrail_reason is not None:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="guardrail_preserve_original",
                latency_ms=structured_result.latency_ms,
                meta={
                    "source": "guardrail_preserve_original",
                    "fallback_reason": guardrail_reason,
                    "guardrail_reason": guardrail_reason,
                },
            )
        return RewriteResult(
            query=text,
            rewritten=text != query,
            reason=structured_result.reason,
            latency_ms=structured_result.latency_ms,
        )

    # 复用现有检索改写行为，作为低风险兜底。
    fallback = await service.rewrite(query)
    # 即便兜底成功但未改写结果，也要显式保留 transform 输出。
    if fallback.reason is None:
        fallback.reason = structured_result.reason or "fallback_rewrite"
    return fallback

async def resolve_merge_context_conflict(
    service,
    *,
    question: str,
    summary_text: str,
    memory_snippet: str,
) -> MergeContextResolutionResult:
    """解决摘要与记忆内容冲突，用于上下文合并。"""
    structured_result = await service._call_prompt_structured(
        "kb_chat/context_merge",
        schema=MergeContextResolutionDecision,
        max_tokens=192,
        question=_normalize_whitespace(question),
        summary_text=_normalize_whitespace(summary_text),
        memory_snippet=_normalize_whitespace(memory_snippet),
    )
    payload = structured_result.payload
    if structured_result.success and isinstance(
        payload, MergeContextResolutionDecision
    ):
        summary = _normalize_whitespace(payload.summary_text)
        notes = _dedupe_keep_order(
            [_normalize_whitespace(str(note)) for note in payload.notes]
        )[:4]
        return MergeContextResolutionResult(
            summary_text=summary,
            keep_memory=bool(payload.keep_memory),
            notes=notes,
            success=True,
            reason=structured_result.reason,
            latency_ms=structured_result.latency_ms,
        )

    return MergeContextResolutionResult(
        summary_text=_normalize_whitespace(summary_text),
        keep_memory=True,
        notes=[],
        success=False,
        reason=structured_result.reason or "fallback_keep_inputs",
        latency_ms=structured_result.latency_ms,
    )

async def classify_complexity(
    service,
    query: str,
    *,
    recall_risk: str | None = None,
    has_multi_target: bool = False,
    is_comparison: bool = False,
) -> ComplexityRouteResult:
    """决定 preprocess 路由策略。"""
    start = time.perf_counter()
    q = _normalize_whitespace(query)
    if not q:
        return ComplexityRouteResult(
            strategy="direct",
            success=False,
            reasoning=_default_complexity_reason("direct"),
            confidence=0.0,
            risk_flags=[],
            decision_version=COMPLEXITY_CLASSIFY_DECISION_VERSION,
            latency_ms=0,
        )

    try:
        prompt = service._prompts.render_with_few_shot(
            "kb_chat/complexity_classify",
            question=q,
            recall_risk=(recall_risk or "unknown"),
            has_multi_target=bool(has_multi_target),
            is_comparison=bool(is_comparison),
        )
    except KeyError:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return service._fallback_complexity_route(
            query=q,
            recall_risk=recall_risk,
            has_multi_target=has_multi_target,
            is_comparison=is_comparison,
            failure_reason="prompt_missing",
            latency_ms=latency_ms,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Prompt render 失败",
            extra={"prompt_key": "kb_chat/complexity_classify", "error": str(exc)},
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return service._fallback_complexity_route(
            query=q,
            recall_risk=recall_risk,
            has_multi_target=has_multi_target,
            is_comparison=is_comparison,
            failure_reason="prompt_error",
            latency_ms=latency_ms,
        )

    structured_result = await service._invoke_model_structured(
        schema=ComplexityDecision,
        user_prompt=prompt,
        max_tokens=256,
    )
    if structured_result.success and isinstance(
        structured_result.payload, ComplexityDecision
    ):
        payload = structured_result.payload
        strategy = str(payload.strategy or "direct").strip().lower()
        if strategy not in {"direct", "decomposition", "multi_query"}:
            strategy = "direct"
        confidence = round(max(0.0, min(1.0, float(payload.confidence))), 4)
        risk_flags = _sanitize_risk_flags(payload.risk_flags)
        decision_version = _normalize_whitespace(payload.decision_version)
        if not decision_version:
            decision_version = COMPLEXITY_CLASSIFY_DECISION_VERSION
        guarded_result = service._apply_complexity_guardrail(
            query=q,
            recall_risk=recall_risk,
            has_multi_target=has_multi_target,
            is_comparison=is_comparison,
            strategy=strategy,
            confidence=confidence,
            risk_flags=risk_flags,
            decision_version=decision_version,
            latency_ms=structured_result.latency_ms,
        )
        if guarded_result is not None:
            return guarded_result
        return ComplexityRouteResult(
            strategy=strategy,
            success=True,
            reasoning=getattr(payload, "reasoning", None),
            failure_reason=None,
            confidence=confidence,
            risk_flags=risk_flags,
            decision_version=decision_version,
            latency_ms=structured_result.latency_ms,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    return service._fallback_complexity_route(
        query=q,
        recall_risk=recall_risk,
        has_multi_target=has_multi_target,
        is_comparison=is_comparison,
        failure_reason=structured_result.reason or "llm_failed_fallback_direct",
        latency_ms=latency_ms,
    )

async def decompose(
    service,
    query: str,
    *,
    enabled: bool | None = None,
) -> QueryListResult:
    """仅通过结构化 LLM 输出将查询拆成子问题。"""
    start = time.perf_counter()
    enabled_flag = True if enabled is None else bool(enabled)
    if not enabled_flag:
        return QueryListResult(
            queries=[], success=False, reason="disabled", latency_ms=0
        )

    q = _normalize_whitespace(query)
    if not q:
        return QueryListResult(
            queries=[], success=False, reason="empty", latency_ms=0
        )

    structured_result = await service._call_prompt_structured(
        "kb_chat/decomposition",
        schema=DecompositionDecision,
        max_tokens=256,
        question=q,
    )
    if structured_result.success and isinstance(
        structured_result.payload, DecompositionDecision
    ):
        payload = structured_result.payload
        spec_queries = [
            _normalize_whitespace(str(spec.get("query") or ""))
            for spec in payload.sub_query_specs
            if isinstance(spec, dict)
        ]
        sub_queries = _dedupe_keep_order([*spec_queries, *payload.sub_queries])[
            : _decomposition_max_sub_queries()
        ]
        if len(sub_queries) >= 2:
            latency_ms = int((time.perf_counter() - start) * 1000)
            normalized_specs: list[dict[str, object]] = []
            for idx, q in enumerate(sub_queries):
                matched = next(
                    (
                        spec
                        for spec in payload.sub_query_specs
                        if isinstance(spec, dict)
                        and _normalize_whitespace(str(spec.get("query") or "")) == q
                    ),
                    None,
                )
                if isinstance(matched, dict):
                    raw_tags_obj = matched.get("coverage_tags")
                    raw_tags: list[object] = (
                        raw_tags_obj if isinstance(raw_tags_obj, list) else []
                    )
                    tags = [
                        _normalize_whitespace(str(tag))
                        for tag in raw_tags
                        if _normalize_whitespace(str(tag))
                    ][:6]
                    raw_priority = matched.get("priority")
                    priority = (
                        int(raw_priority)
                        if isinstance(raw_priority, int)
                        else idx + 1
                    )
                    purpose = _normalize_whitespace(
                        str(matched.get("purpose") or "")
                    )
                else:
                    tags = []
                    priority = idx + 1
                    purpose = ""
                normalized_specs.append(
                    {
                        "query": q,
                        "priority": max(1, min(priority, 8)),
                        "coverage_tags": tags,
                        "purpose": purpose,
                    }
                )
            plan: dict[str, object] = {
                "strategy": str(payload.strategy or "decomposition"),
                "version": _normalize_whitespace(payload.plan_version)
                or "kb_chat_decomposition_plan_v2",
                "sub_query_specs": normalized_specs,
                "risk_flags": _sanitize_risk_flags(payload.risk_flags),
                "reasoning": _normalize_whitespace(payload.reasoning),
            }
            return QueryListResult(
                queries=sub_queries,
                success=True,
                reason="llm_structured",
                latency_ms=latency_ms,
                plan=plan,
                diagnostics={
                    "source": "llm_structured",
                    "spec_count": len(normalized_specs),
                },
            )
        structured_result = StructuredCallResult(
            payload=payload,
            success=False,
            reason="llm_invalid_decomposition_insufficient_subqueries",
            latency_ms=structured_result.latency_ms,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    fallback_reason = structured_result.reason or "llm_structured_fallback_original"
    fallback_specs = _rule_based_decomposition_candidates(q)
    if len(fallback_specs) >= 2:
        fallback_queries = [
            _normalize_whitespace(str(spec.get("query") or ""))
            for spec in fallback_specs
            if _normalize_whitespace(str(spec.get("query") or ""))
        ]
        risk_flags = ["llm_fallback"]
        if _looks_compare_or_multi_target(q):
            risk_flags.extend(["comparison", "multi_target"])
        return QueryListResult(
            queries=fallback_queries,
            success=False,
            reason=fallback_reason,
            latency_ms=latency_ms,
            plan={
                "strategy": "decomposition",
                "version": "kb_chat_decomposition_plan_v2",
                "sub_query_specs": fallback_specs,
                "risk_flags": _sanitize_risk_flags(risk_flags),
                "reasoning": fallback_reason,
            },
            diagnostics={"source": "heuristic_decomposition"},
        )
    return QueryListResult(
        queries=[q],
        success=False,
        reason=fallback_reason,
        latency_ms=latency_ms,
        plan={
            "strategy": "direct",
            "version": "kb_chat_decomposition_plan_v2",
            "sub_query_specs": [
                {
                    "query": q,
                    "priority": 1,
                    "coverage_tags": [],
                    "purpose": "fallback_original_query",
                }
            ],
            "risk_flags": ["llm_fallback"],
            "reasoning": fallback_reason,
        },
        diagnostics={"source": "fallback_original"},
    )

async def generate_variants(
    service,
    query: str,
    *,
    enabled: bool | None = None,
) -> QueryListResult:
    """生成恰好 3 个 multi-query 变体，并提供安全兜底。"""
    start = time.perf_counter()
    enabled_flag = True if enabled is None else bool(enabled)
    if not enabled_flag:
        return QueryListResult(
            queries=[], success=False, reason="disabled", latency_ms=0
        )

    q = _normalize_whitespace(query)
    if not q:
        return QueryListResult(
            queries=[], success=False, reason="empty", latency_ms=0
        )

    structured_result = await service._call_prompt_structured(
        "kb_chat/multi_query",
        schema=MultiQueryDecision,
        max_tokens=256,
        question=q,
    )
    if structured_result.success and isinstance(
        structured_result.payload, MultiQueryDecision
    ):
        fixed_variants, completed, invalid_reason = (
            _coerce_fixed_multi_query_variants(
                structured_result.payload.queries,
                original_query=q,
            )
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        if invalid_reason and not completed:
            return QueryListResult(
                queries=fixed_variants,
                success=False,
                reason=f"llm_invalid_multi_query_{invalid_reason}",
                latency_ms=latency_ms,
            )
        if invalid_reason and completed:
            return QueryListResult(
                queries=fixed_variants,
                success=True,
                reason="llm_structured_with_rule_completion",
                latency_ms=latency_ms,
            )
        return QueryListResult(
            queries=fixed_variants,
            success=True,
            reason=(
                "llm_structured_with_rule_completion"
                if completed
                else "llm_structured"
            ),
            latency_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    fixed_variants, _, _ = _coerce_fixed_multi_query_variants([], original_query=q)
    return QueryListResult(
        queries=fixed_variants,
        success=False,
        reason="llm_failed_rule_completion",
        latency_ms=latency_ms,
    )

async def hyde(
    service,
    query: str,
) -> QueryListResult:
    """HyDE 生成器，优先使用 LLM，并提供安全兜底。"""
    start = time.perf_counter()
    q = _normalize_whitespace(query)
    if not q:
        return QueryListResult(
            queries=[], success=False, reason="empty", latency_ms=0
        )

    structured_result = await service._call_prompt_structured(
        "kb_chat/hyde",
        schema=HyDEBatchDecision,
        max_tokens=768,
        question=q,
        num_hypotheses=_hyde_num_hypotheses(),
    )
    if structured_result.success and isinstance(
        structured_result.payload, HyDEBatchDecision
    ):
        docs = _normalize_hyde_documents(
            structured_result.payload.hypothetical_documents,
            limit=_hyde_num_hypotheses(),
        )
        if docs:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return QueryListResult(
                queries=docs,
                success=True,
                reason="llm_structured",
                latency_ms=latency_ms,
            )

    latency_ms = int((time.perf_counter() - start) * 1000)
    return QueryListResult(
        queries=[],
        success=False,
        reason="llm_failed_fallback_empty",
        latency_ms=latency_ms,
    )

