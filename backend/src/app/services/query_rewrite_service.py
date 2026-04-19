"""查询增强服务：提供 rewrite / clarify / fanout 辅助能力。

This module is shared by:
- RetrievalService's optional single-query rewrite
- KB Chat agentic preprocess (coref/normalize/ambiguity/decompose/multi-query/HyDE)

Keep outputs JSON-friendly so they can be safely stored in LangGraph state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any, cast

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ValidationError

from app.agents.kb_chat_agentic.schemas import COMPLEXITY_CLASSIFY_DECISION_VERSION
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.prompts import get_prompt_loader
from app.services import query_rewrite_basic_ops, query_rewrite_planning_ops
from app.services.query_rewrite_contracts import (
    AmbiguityResult,
    ComplexityRouteResult,
    MergeContextResolutionResult,
    QueryListResult,
    RetrievalPlanResult,
    RewriteResult,
    StructuredCallResult,
    _AsyncInvoker,
)
from app.services.query_rewrite_items import build_query_items
from app.services.query_rewrite_structured import (
    _structured_result_debug_snapshot,
    coerce_structured_result_payload,
)
from app.services.query_rewrite_text import (
    _contains_coref_marker,
    _default_ambiguity_reason,
    _default_complexity_reason,
    _guardrail_complexity_reason,
    _looks_compare_or_multi_target,
    _looks_explicit_decomposition_query,
    _looks_stable_overview_query,
    _looks_term_alias_query,
    _normalize_reason_code,
    _normalize_whitespace,
    _resolve_ambiguity_reason_label,
    _sanitize_risk_flags,
    _structured_call_max_attempts,
    _structured_call_retryable_reasons,
)

logger = logging.getLogger(__name__)

__all__ = [
    "COMPLEXITY_CLASSIFY_DECISION_VERSION",
    "QueryRewriteService",
    "RewriteResult",
    "build_query_items",
    "coerce_structured_result_payload",
    "_looks_stable_overview_query",
]
class QueryRewriteService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._prompts = get_prompt_loader()
        self._structured_chat_model: BaseChatModel | None = None
        self._structured_agents: dict[type[BaseModel], _AsyncInvoker] = {}

    def _get_structured_chat_model(self) -> BaseChatModel:
        if self._structured_chat_model is None:
            self._structured_chat_model = create_chat_model(
                settings=self._settings,
                use_previous_response_id=False,
            )
        return self._structured_chat_model

    def _get_structured_agent(self, schema: type[BaseModel]) -> _AsyncInvoker:
        agent = self._structured_agents.get(schema)
        if agent is not None:
            return agent
        agent = cast(
            _AsyncInvoker,
            create_agent(
                model=self._get_structured_chat_model(),
                tools=[],
                system_prompt="",
                response_format=schema,
            ),
        )
        self._structured_agents[schema] = agent
        return agent

    @staticmethod
    def _classify_structured_error(exc: Exception) -> str:
        name = exc.__class__.__name__
        if name in {
            "StructuredOutputValidationError",
            "ValidationError",
            "OutputParserException",
        }:
            return "invalid_schema"
        if name == "MultipleStructuredOutputsError":
            return "multiple_structured_outputs"
        return "error"

    @staticmethod
    def _resolve_ambiguity_business_reason(
        *,
        ambiguous: bool,
        model_reason: str | None,
        reason_code: str | None,
    ) -> str:
        normalized_reason = _normalize_whitespace(model_reason or "")
        if normalized_reason:
            return normalized_reason
        normalized_code = _normalize_reason_code(reason_code)
        if ambiguous:
            return _resolve_ambiguity_reason_label(normalized_code) or (
                _default_ambiguity_reason(ambiguous=True)
            )
        return _default_ambiguity_reason(ambiguous=False)

    @staticmethod
    def _fallback_complexity_route(
        *,
        query: str,
        recall_risk: str | None,
        has_multi_target: bool,
        is_comparison: bool,
        failure_reason: str | None,
        latency_ms: int,
    ) -> ComplexityRouteResult:
        normalized_query = _normalize_whitespace(query)
        normalized_risk = _normalize_whitespace(recall_risk or "").lower()
        heuristic_compare_or_multi_target = _looks_compare_or_multi_target(
            normalized_query
        )
        heuristic_term_alias = _looks_term_alias_query(normalized_query)
        query_has_mixed_language = (
            re.search(r"[A-Za-z]", normalized_query) is not None
            and re.search(r"[\u4e00-\u9fff]", normalized_query) is not None
        )
        if is_comparison or has_multi_target or heuristic_compare_or_multi_target:
            risk_flags: list[str] = []
            if is_comparison or heuristic_compare_or_multi_target:
                risk_flags.append("comparison")
            if has_multi_target or heuristic_compare_or_multi_target:
                risk_flags.append("multi_target")
            return ComplexityRouteResult(
                strategy="decomposition",
                success=False,
                reasoning=_default_complexity_reason("decomposition"),
                failure_reason=failure_reason,
                confidence=0.35,
                risk_flags=risk_flags,
                decision_version=COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=latency_ms,
            )
        if normalized_risk == "high" or heuristic_term_alias:
            risk_flags = ["recall_risk_high"] if normalized_risk == "high" else []
            if heuristic_term_alias:
                risk_flags.append("term_alias")
            if heuristic_term_alias and query_has_mixed_language:
                risk_flags.append("mixed_language")
            return ComplexityRouteResult(
                strategy="multi_query",
                success=False,
                reasoning=_default_complexity_reason("multi_query"),
                failure_reason=failure_reason,
                confidence=0.28,
                risk_flags=_sanitize_risk_flags(risk_flags),
                decision_version=COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=latency_ms,
            )
        return ComplexityRouteResult(
            strategy="direct",
            success=False,
            reasoning=_default_complexity_reason("direct"),
            failure_reason=failure_reason,
            confidence=0.0,
            risk_flags=["llm_failed_fallback_direct"] if failure_reason else [],
            decision_version=COMPLEXITY_CLASSIFY_DECISION_VERSION,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _apply_complexity_guardrail(
        *,
        query: str,
        recall_risk: str | None,
        has_multi_target: bool,
        is_comparison: bool,
        strategy: str,
        confidence: float,
        risk_flags: list[str] | None,
        decision_version: str | None,
        latency_ms: int | None,
    ) -> ComplexityRouteResult | None:
        normalized_query = _normalize_whitespace(query)
        normalized_risk = _normalize_whitespace(recall_risk or "").lower()
        current_risk_flags = _sanitize_risk_flags(risk_flags or [])

        if strategy != "multi_query":
            return None

        if (
            is_comparison
            or has_multi_target
            or _looks_explicit_decomposition_query(normalized_query)
        ):
            return ComplexityRouteResult(
                strategy="decomposition",
                success=True,
                reasoning=_guardrail_complexity_reason("decomposition"),
                failure_reason=None,
                confidence=confidence,
                risk_flags=_sanitize_risk_flags(
                    [
                        *current_risk_flags,
                        "comparison" if is_comparison else "",
                        "multi_target",
                    ]
                ),
                decision_version=decision_version
                or COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=latency_ms,
            )

        if (
            normalized_risk != "high"
            and not _looks_term_alias_query(normalized_query)
            and _looks_stable_overview_query(normalized_query)
        ):
            return ComplexityRouteResult(
                strategy="direct",
                success=True,
                reasoning=_guardrail_complexity_reason("direct"),
                failure_reason=None,
                confidence=confidence,
                risk_flags=_sanitize_risk_flags(
                    [*current_risk_flags, "stable_overview"]
                ),
                decision_version=decision_version
                or COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=latency_ms,
            )

        return None

    async def _invoke_structured(
        self,
        *,
        agent: _AsyncInvoker,
        schema: type[BaseModel],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        _ = max_tokens
        request = {"messages": [{"role": "user", "content": user_prompt}]}
        try:
            result = await agent.ainvoke(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason=self._classify_structured_error(exc),
            )

        if not isinstance(result, dict):
            return StructuredCallResult(
                payload=None, success=False, reason="empty_structured_response"
            )
        structured_payload = result.get("structured_response")
        if structured_payload is None:
            return StructuredCallResult(
                payload=None, success=False, reason="empty_structured_response"
            )
        if isinstance(structured_payload, schema):
            return StructuredCallResult(payload=structured_payload, success=True)
        try:
            payload = schema.model_validate(structured_payload)
        except ValidationError:
            return StructuredCallResult(
                payload=None, success=False, reason="invalid_schema"
            )
        return StructuredCallResult(payload=payload, success=True)

    async def _invoke_model_structured(
        self,
        *,
        schema: type[BaseModel],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        from langchain.messages import HumanMessage

        try:
            structured_model = cast(
                _AsyncInvoker,
                cast(Any, self._get_structured_chat_model().bind(max_tokens=max_tokens)).with_structured_output(
                schema,
                method="function_calling",
                include_raw=True,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "structured_output_init_failed",
                        "schema": schema.__name__,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
            logger.warning(
                "Structured output 初始化失败",
                extra={
                    "schema": schema.__name__,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            )
            return StructuredCallResult(
                payload=None,
                success=False,
                reason=self._classify_structured_error(exc),
            )

        request = [HumanMessage(content=user_prompt)]
        try:
            result = await structured_model.ainvoke(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "structured_output_invoke_failed",
                        "schema": schema.__name__,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
            logger.warning(
                "Structured output 调用失败",
                extra={
                    "schema": schema.__name__,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            )
            return StructuredCallResult(
                payload=None,
                success=False,
                reason=self._classify_structured_error(exc),
            )

        payload, reason = coerce_structured_result_payload(result=result, schema=schema)
        if payload is None:
            print(
                json.dumps(
                    {
                        "event": "structured_output_parse_failed",
                        "schema": schema.__name__,
                        "reason": reason,
                        **_structured_result_debug_snapshot(result),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                file=sys.stderr,
                flush=True,
            )
            logger.warning(
                "Structured output 解析失败",
                extra={
                    "schema": schema.__name__,
                    "reason": reason,
                    **_structured_result_debug_snapshot(result),
                },
            )
            return StructuredCallResult(payload=None, success=False, reason=reason)
        return StructuredCallResult(payload=payload, success=True)

    async def rewrite(
        self,
        query: str,
        *,
        max_tokens: int | None = None,
        prompt_key: str = "retrieval/query_rewrite",
    ) -> RewriteResult:
        return await query_rewrite_basic_ops.rewrite(
            service=self,
            query=query,
            max_tokens=max_tokens,
            prompt_key=prompt_key,
        )

    async def resolve_reference(
        self,
        query: str,
        *,
        enabled: bool = True,
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ) -> RewriteResult:
        return await query_rewrite_basic_ops.resolve_reference(
            service=self,
            query=query,
            enabled=enabled,
            recent_turns=recent_turns,
            summary_text=summary_text,
            memory_snippet=memory_snippet,
        )

    async def coref_rewrite(
        self,
        query: str,
        *,
        enabled: bool = True,
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ) -> RewriteResult:
        return await query_rewrite_basic_ops.coref_rewrite(
            service=self,
            query=query,
            enabled=enabled,
            recent_turns=recent_turns,
            summary_text=summary_text,
            memory_snippet=memory_snippet,
        )

    async def normalize_rewrite(
        self,
        query: str,
    ) -> RewriteResult:
        return await query_rewrite_basic_ops.normalize_rewrite(
            service=self,
            query=query,
        )
    async def plan_retrieval_budget(
        self,
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
        return await query_rewrite_planning_ops.plan_retrieval_budget(
            service=self,
            question=question,
            normalized_query=normalized_query,
            complexity_level=complexity_level,
            query_items=query_items,
            retry_count=retry_count,
            failure_reason=failure_reason,
            max_top_k=max_top_k,
            fallback_budget=fallback_budget,
        )

    async def ambiguity_check(
        self,
        query: str,
        *,
        enabled: bool | None = None,
        coref_meta: dict[str, object] | None = None,
    ) -> AmbiguityResult:
        return await query_rewrite_planning_ops.ambiguity_check(
            service=self,
            query=query,
            enabled=enabled,
            coref_meta=coref_meta,
        )

    async def transform_query(
        self,
        query: str,
        *,
        reason: str,
        hint: str | None = None,
        enabled: bool = True,
    ) -> RewriteResult:
        return await query_rewrite_planning_ops.transform_query(
            service=self,
            query=query,
            reason=reason,
            hint=hint,
            enabled=enabled,
        )

    async def resolve_merge_context_conflict(
        self,
        *,
        question: str,
        summary_text: str,
        memory_snippet: str,
    ) -> MergeContextResolutionResult:
        return await query_rewrite_planning_ops.resolve_merge_context_conflict(
            service=self,
            question=question,
            summary_text=summary_text,
            memory_snippet=memory_snippet,
        )

    async def classify_complexity(
        self,
        query: str,
        *,
        recall_risk: str | None = None,
        has_multi_target: bool = False,
        is_comparison: bool = False,
    ) -> ComplexityRouteResult:
        return await query_rewrite_planning_ops.classify_complexity(
            service=self,
            query=query,
            recall_risk=recall_risk,
            has_multi_target=has_multi_target,
            is_comparison=is_comparison,
        )

    async def decompose(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        return await query_rewrite_planning_ops.decompose(
            service=self,
            query=query,
            enabled=enabled,
        )

    async def generate_variants(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        return await query_rewrite_planning_ops.generate_variants(
            service=self,
            query=query,
            enabled=enabled,
        )

    async def hyde(
        self,
        query: str,
    ) -> QueryListResult:
        return await query_rewrite_planning_ops.hyde(
            service=self,
            query=query,
        )
    def _is_ambiguous_heuristic(self, query: str) -> bool:
        q = _normalize_whitespace(query)
        if not q:
            return True
        if len(q) <= 2:
            return True
        # 仅用于护栏判断：短问题同时命中指代词时，通常意味着存在歧义。
        if len(q) <= 10 and _contains_coref_marker(q):
            return True
        return False

    async def _call_prompt_structured(
        self,
        prompt_key: str,
        *,
        schema: type[BaseModel],
        max_tokens: int,
        **kwargs: object,
    ) -> StructuredCallResult:
        """调用提示词，并通过 with_structured_output(..., method="function_calling") 解析结构化输出。"""
        try:
            prompt = self._prompts.render_with_few_shot(prompt_key, **kwargs)
        except KeyError:
            return StructuredCallResult(
                payload=None, success=False, reason="prompt_missing", latency_ms=0
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Prompt render 失败",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return StructuredCallResult(
                payload=None, success=False, reason="prompt_error", latency_ms=0
            )

        start_time = time.perf_counter()
        structured: StructuredCallResult | None = None
        max_attempts = _structured_call_max_attempts()
        retryable_reasons = _structured_call_retryable_reasons()
        for attempt in range(1, max_attempts + 1):
            try:
                structured = await self._invoke_model_structured(
                    schema=schema,
                    user_prompt=prompt,
                    max_tokens=max_tokens,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                logger.warning(
                    "Prompt LLM structured 调用失败",
                    extra={"prompt_key": prompt_key, "error": str(exc)},
                )
                return StructuredCallResult(
                    payload=None, success=False, reason="error", latency_ms=latency_ms
                )
            reason = str(structured.reason or "")
            if (
                structured.success
                or attempt >= max_attempts
                or reason not in retryable_reasons
            ):
                break
            print(
                json.dumps(
                    {
                        "event": "structured_output_retry",
                        "prompt_key": prompt_key,
                        "schema": schema.__name__,
                        "attempt": attempt + 1,
                        "retry_reason": reason,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
            logger.warning(
                "Structured output 返回可重试失败，准备重试",
                extra={
                    "prompt_key": prompt_key,
                    "schema": schema.__name__,
                    "attempt": attempt + 1,
                    "retry_reason": reason,
                },
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        if structured is None:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason="error",
                latency_ms=latency_ms,
            )
        if not structured.success or structured.payload is None:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason=structured.reason or "invalid_schema",
                latency_ms=latency_ms,
            )
        return StructuredCallResult(
            payload=structured.payload,
            success=True,
            reason=structured.reason,
            latency_ms=latency_ms,
        )

    async def _call_llm(self, prompt: str, *, max_tokens: int) -> str:
        from langchain.messages import HumanMessage

        model = create_chat_model(settings=self._settings)
        model = model.bind(max_tokens=max_tokens)

        def _run() -> object:
            return model.invoke([HumanMessage(content=prompt)])

        result = await asyncio.to_thread(_run)
        return getattr(result, "content", "") or ""
