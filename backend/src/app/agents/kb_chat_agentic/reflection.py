"""KB Chat agentic ReflectionLayer nodes (relevance / answer-review).

These nodes are designed to be:
- Minimal & production-safe (fallbacks)
- Serializable-friendly (only write JSON-ish values to state)
- Budget-aware (bind routing to loop_counts rounds/retries budgets)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.core.settings import Settings, get_settings
from app.prompts import get_prompt_loader
from app.services.evidence_guardrails import (
    extract_citation_labels,
    normalize_citation_label,
)
from app.services.query_rewrite_service import (
    HYDE_REGENERATE_ON_RETRY,
    QueryRewriteService,
    build_query_items,
)

from .budget import now_iso
from .json_safety import ensure_json_safe
from .runtime_config import (
    hyde_enabled,
    normalize_alias_max,
    normalize_llm_enabled,
    normalize_timeout_seconds,
    query_rewrite_enabled,
    retrieval_top_k,
)
from .schemas import AnswerReviewDecision, DocGraderDecision

_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
_CITATION_ONLY_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
    # Backward compatibility for old checkpoints.
    "missing_or_invalid_citations",
}


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _get_loop_counts(state: dict) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _total_rounds_exceeded(loop_counts: dict[str, int], settings: Settings) -> bool:
    return loop_counts.get("total_rounds", 0) >= int(settings.kb_chat_max_total_rounds)


def _normalize_citation_label(value: str) -> str:
    return normalize_citation_label(value)


def _extract_evidence_labels(final_context: str) -> dict[str, str]:
    if not final_context:
        return {}
    labels: dict[str, str] = {}
    for match in _EVIDENCE_LINE_RE.finditer(final_context):
        label = _normalize_citation_label(match.group(1))
        if not label:
            continue
        labels.setdefault(label.casefold(), label)
    return labels


def _extract_evidence_count(final_context: str) -> int:
    if not final_context:
        return 0
    return sum(1 for _ in _EVIDENCE_LINE_RE.finditer(final_context))


def _partition_citations(
    answer: str, *, allowed_labels: dict[str, str]
) -> tuple[list[str], set[str], set[str]]:
    if not answer or not allowed_labels:
        return [], set(), set()
    all_citations = extract_citation_labels(answer)
    valid_found: set[str] = set()
    invalid_found: set[str] = set()
    for label in all_citations:
        key = label.casefold()
        if key in allowed_labels:
            valid_found.add(allowed_labels[key])
        else:
            invalid_found.add(label)
    return all_citations, valid_found, invalid_found


def _render_prompt_or_default(prompt_key: str, default: str) -> str:
    prompts = get_prompt_loader()
    try:
        return prompts.render_with_few_shot(prompt_key)
    except KeyError:
        return default


_StructuredT = TypeVar("_StructuredT", bound=BaseModel)


def _classify_structured_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "StructuredOutputValidationError":
        return "invalid_schema"
    if name == "MultipleStructuredOutputsError":
        return "multiple_structured_outputs"
    return "error"


async def _judge_structured(
    *,
    chat_model: ChatOpenAI,
    schema: type[_StructuredT],
    system: str,
    user: str,
) -> tuple[_StructuredT | None, str | None]:
    agent = create_agent(
        model=chat_model,
        tools=[],
        system_prompt=system,
        response_format=schema,
    )
    request = {"messages": [{"role": "user", "content": user}]}
    try:
        result = await agent.ainvoke(request)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, _classify_structured_error(exc)
    if not isinstance(result, dict):
        return None, "empty_structured_response"
    structured_payload = result.get("structured_response")
    if structured_payload is None:
        return None, "empty_structured_response"
    if isinstance(structured_payload, schema):
        return structured_payload, None
    try:
        payload = schema.model_validate(structured_payload)
    except ValidationError:
        return None, "invalid_schema"
    return payload, None


def _merge_stage_summary(
    state: dict, key: str, summary: dict[str, Any]
) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    settings = get_settings()
    safe_summary = ensure_json_safe(
        summary, settings=settings, label=f"stage_summaries.{key}"
    )
    merged = {**stage_summaries, key: safe_summary}
    merged = ensure_json_safe(merged, settings=settings, label="stage_summaries")
    return {"stage_summaries": merged}


def _merge_reflection(state: dict, patch: dict[str, Any]) -> dict[str, Any]:
    reflection = state.get("reflection")
    if not isinstance(reflection, dict):
        reflection = {}
    return {"reflection": {**reflection, **patch}}


def _set_final_answer_for_exit(
    state: dict, answer: str, *, reason: str
) -> dict[str, Any]:
    # ForceExit node prefers final_answer; set it explicitly so we don't leak history AIMessage.
    return {
        "final_answer": answer,
        **_merge_reflection(state, {"action": "force_exit", "reason": reason}),
    }


def _force_exit_requested(state: dict) -> bool:
    reflection = state.get("reflection")
    return isinstance(reflection, dict) and reflection.get("action") == "force_exit"


def _resolve_query_text(state: dict) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


async def kb_retrieve_context(
    state: dict,
    *,
    settings: Settings,
    kb_tool: BaseTool,
) -> dict[str, Any]:
    """Run kb_retrieve once and store the resulting Top-N context into state.final_context."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return _set_final_answer_for_exit(state, "", reason="max_total_rounds")
    query = _resolve_query_text(state)
    memory_keys = state.get("memory_keys")
    kb_ids = memory_keys.get("kb_ids") if isinstance(memory_keys, dict) else None
    if not isinstance(kb_ids, list):
        kb_ids = None

    retrieval_round = max(loop_counts.get("retrieval_retries", 0), 0)
    retrieval_reason: str | None = None
    try:
        payload: dict[str, Any] = {
            "query": query,
            "kb_ids": kb_ids,
            "top_k": retrieval_top_k(state, settings),
            "retrieval_round": retrieval_round,
        }
        query_items = state.get("query_items")
        if isinstance(query_items, list) and query_items:
            # Pass fanout query bundle to kb_retrieve so RetrievalService.retrieve_layer() can do cross-query fusion.
            payload["query_items"] = query_items
        context = await kb_tool.ainvoke(payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        retrieval_reason = "exception"
        context = "（未找到相关内容）"

    final_context = _as_str(context).strip()
    evidence_count = _extract_evidence_count(final_context)

    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    metrics = {
        **metrics,
        "retrieval_layer": {
            "evidence_count": evidence_count,
            "attempted": True,
        },
    }
    metrics = ensure_json_safe(metrics, settings=settings, label="metrics")

    updates: dict[str, Any] = {
        "final_context": final_context,
        "metrics": metrics,
        **_merge_stage_summary(
            state,
            "retrieval_layer",
            {
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "evidence_count": evidence_count,
                "reason": retrieval_reason,
                "completed_at": now_iso(),
            },
        ),
    }
    return updates


async def doc_grader(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Grade retrieval relevance; if failed, downstream routing may transform query + retry."""
    start = time.perf_counter()
    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    evidence_labels = _extract_evidence_labels(final_context)

    passed = False
    reason = "no_evidence"
    missing_constraints: list[str] = []
    fallback_used = False
    fallback_reason: str | None = None
    if evidence_labels and "未找到相关内容" not in final_context:
        system_prompt = _render_prompt_or_default(
            "kb_chat/doc_grader",
            (
                "You are a strict retrieval relevance grader. "
                "Determine whether the retrieved snippets are directly relevant to the question "
                "and sufficient to support the answer."
                ' Output JSON only: {"passed": true/false, "reason": "..."}'
            ),
        )
        judge: DocGraderDecision | None = None
        judge, fallback_reason = await _judge_structured(
            chat_model=chat_model,
            schema=DocGraderDecision,
            system=system_prompt,
            user=f"问题：{question}\n\n检索片段：\n{final_context[:4000]}",
        )
        if judge is None:
            fallback_used = True
        if isinstance(judge, DocGraderDecision):
            passed = bool(judge.passed)
            reason = judge.reason
            missing_constraints = [
                _as_str(item).strip()
                for item in (judge.missing_constraints or [])
                if _as_str(item).strip()
            ][:3]
        else:
            policy = settings.kb_chat_grader_fail_policy
            passed = policy == "open"
            reason = fallback_reason or (
                "fallback_open" if passed else "fallback_closed"
            )
            if fallback_reason is None:
                fallback_reason = "invalid_schema"
    elif not evidence_labels:
        missing_constraints = ["相关证据"]

    if not passed and not missing_constraints:
        if reason == "insufficient":
            missing_constraints = ["关键约束"]
        elif reason == "too_broad":
            missing_constraints = ["限定条件"]
        elif reason == "needs_clarification":
            missing_constraints = ["对象/范围/时间/口径"]
        elif reason == "no_evidence":
            missing_constraints = ["相关证据"]

    hint = "、".join(missing_constraints[:3])

    action = "none" if passed else "transform_query"

    updates: dict[str, Any] = {
        **_merge_reflection(
            state,
            {
                "relevance_passed": passed,
                "action": action,
                "reason": reason,
                "hint": hint,
            },
        ),
        **_merge_stage_summary(
            state,
            "doc_grader",
            {
                "passed": passed,
                "reason": reason,
                "missing_constraints": missing_constraints,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }
    return updates


async def generate_draft(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Generate a draft answer using ONLY Top-N final_context; do not append to messages."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)

    # Budget accounting: count each generation as one "round".
    loop_counts = {**loop_counts, "total_rounds": loop_counts["total_rounds"] + 1}

    if _total_rounds_exceeded(loop_counts, settings):
        # Prefer current best draft if any.
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state, _as_str(state.get("draft_answer")), reason="max_total_rounds"
            ),
        }
    if loop_counts["generation_retries"] > int(settings.kb_chat_max_generation_retries):
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state,
                _as_str(state.get("draft_answer")),
                reason="max_generation_retries",
            ),
        }

    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    prompts = get_prompt_loader()
    system_prompt = prompts.render_with_few_shot('kb_chat/system')

    user = f"参考内容：\n{final_context}\n\n问题：{question}"

    model = chat_model.bind(max_tokens=1024)
    try:
        msg = await model.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user)]
        )
        draft = _as_str(getattr(msg, "content", "")).strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        draft = ""

    if not draft:
        draft = "根据现有资料无法回答该问题（生成失败）。"

    return {
        "loop_counts": loop_counts,
        "draft_answer": draft,
        # Keep final_answer aligned so ForceExit can always return something sane.
        "final_answer": draft,
        **_merge_stage_summary(
            state,
            "generator",
            {
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def answer_review(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Review draft answer in one pass: factual support + answerability + relevance."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    draft = _as_str(state.get("draft_answer")).strip()

    passed = False
    reason = "empty"
    missing_citations: list[str] = []
    unsupported_claims: list[str] = []
    fallback_used = False
    fallback_reason: str | None = None
    evidence_labels = _extract_evidence_labels(final_context)
    all_citations, valid_citations, invalid_citations = _partition_citations(
        draft, allowed_labels=evidence_labels
    )
    if not draft:
        reason = "empty"
    elif not evidence_labels:
        reason = "no_evidence"
    elif not all_citations:
        reason = "missing_citations"
    elif invalid_citations:
        reason = "invalid_citations"
    else:
        system_prompt = _render_prompt_or_default(
            "kb_chat/answer_review",
            (
                "你是严格的知识库回答审查器。"
                "请同时判断回答是否被参考内容支持且引用有效、并且是否直接回答问题。"
                '仅输出 JSON：{"passed": true/false, "reason": "..."}。'
            ),
        )
        judge: AnswerReviewDecision | None = None
        judge, fallback_reason = await _judge_structured(
            chat_model=chat_model,
            schema=AnswerReviewDecision,
            system=system_prompt,
            user=(
                f"问题：{question}\n\n参考内容：\n{final_context[:4000]}"
                f"\n\n回答：\n{draft[:2000]}"
            ),
        )
        if judge is None:
            fallback_used = True
        if isinstance(judge, AnswerReviewDecision):
            passed = bool(judge.passed)
            reason = judge.reason
            missing_citations = [
                _as_str(item).strip()
                for item in (judge.missing_citations or [])
                if _as_str(item).strip()
            ][:3]
            unsupported_claims = [
                _as_str(item).strip()
                for item in (judge.unsupported_claims or [])
                if _as_str(item).strip()
            ][:3]
        else:
            policy = settings.kb_chat_grader_fail_policy
            passed = policy == "open"
            reason = fallback_reason or (
                "fallback_open" if passed else "fallback_closed"
            )
            if fallback_reason is None:
                fallback_reason = "invalid_schema"

    loop_counts_updates = loop_counts
    action = "none" if passed else "transform_query"
    best_answer_updates: dict[str, Any] = {}
    best_answer_meta: dict[str, Any] | None = None
    if passed:
        if draft:
            best_answer_meta = {
                "from_node": "answer_review",
                "reason": reason,
                "retrieval_round": max(loop_counts.get("retrieval_retries", 0), 0),
                "total_rounds": loop_counts.get("total_rounds", 0),
                "completed_at": now_iso(),
            }
            best_answer_updates = {
                "best_answer": draft,
                "best_answer_meta": best_answer_meta,
            }

    return {
        "loop_counts": loop_counts_updates,
        **best_answer_updates,
        **_merge_reflection(
            state,
            {
                "review_passed": passed,
                "action": action,
                "reason": reason,
            },
        ),
        **_merge_stage_summary(
            state,
            "answer_review",
            {
                "passed": passed,
                "reason": reason,
                "best_answer": draft if passed and draft else None,
                "best_answer_meta": best_answer_meta,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "citation_count": len(all_citations),
                "valid_citation_count": len(valid_citations),
                "invalid_citations": sorted(invalid_citations),
                "missing_citations": missing_citations,
                "unsupported_claims": unsupported_claims,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def transform_query_for_retry(
    state: dict, *, settings: Settings
) -> dict[str, Any]:
    """Transform query and bump retrieval_retries (budget-aware)."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)

    loop_counts = {
        **loop_counts,
        "retrieval_retries": loop_counts["retrieval_retries"] + 1,
    }
    if loop_counts["retrieval_retries"] > int(settings.kb_chat_max_retrieval_retries):
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state,
                _as_str(state.get("draft_answer")),
                reason="max_retrieval_retries",
            ),
        }

    current = _resolve_query_text(state)
    reflection = state.get("reflection")
    reason = reflection.get("reason") if isinstance(reflection, dict) else None
    hint = reflection.get("hint") if isinstance(reflection, dict) else None

    new_query = current
    normalized_meta: dict[str, Any] = {}
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.transform_query(
            current,
            reason=_as_str(reason) or "retry",
            hint=_as_str(hint) or None,
            timeout_seconds=0,
            enabled=query_rewrite_enabled(state, settings),
        )
        if result.query.strip():
            new_query = result.query.strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        new_query = current

    try:
        svc = QueryRewriteService(settings=settings)
        normalize_result = await svc.normalize_rewrite(
            new_query,
            llm_enabled=normalize_llm_enabled(state, settings),
            alias_limit=normalize_alias_max(state, settings),
            timeout_seconds=normalize_timeout_seconds(state, settings),
        )
        if normalize_result.query.strip():
            new_query = normalize_result.query.strip()
        if isinstance(normalize_result.meta, dict):
            normalized_meta = normalize_result.meta
    except asyncio.CancelledError:
        raise
    except Exception:
        normalized_meta = {}

    hyde_docs: list[str] = []
    hyde_reason: str | None = None
    hyde_should_regenerate = HYDE_REGENERATE_ON_RETRY and hyde_enabled(state, settings)
    if hyde_should_regenerate:
        try:
            svc = QueryRewriteService(settings=settings)
            hyde_result = await svc.hyde(new_query, enabled=True)
            hyde_docs = [
                value
                for value in hyde_result.queries
                if isinstance(value, str) and value.strip()
            ]
            hyde_reason = hyde_result.reason
        except asyncio.CancelledError:
            raise
        except Exception:
            hyde_docs = []
            hyde_reason = "error"

    # Keep query bundle consistent: after transform, rebuild retrieval inputs.
    aliases = normalized_meta.get("aliases") if isinstance(normalized_meta.get("aliases"), list) else []
    query_items = build_query_items(
        main_query=new_query,
        variants=[str(v) for v in aliases if isinstance(v, str)],
        hyde_docs=hyde_docs or None,
        hyde_note="retry_regenerated" if hyde_docs else None,
    )

    return {
        "loop_counts": loop_counts,
        "normalized_query": new_query,
        "normalized_meta": normalized_meta,
        "coref_query": new_query,
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": hyde_docs,
        "query_items": query_items,
        **_merge_reflection(
            state,
            {
                "action": "transform_query",
                "reason": _as_str(reason) or "retry",
                "hint": _as_str(hint),
            },
        ),
        **_merge_stage_summary(
            state,
            "transform_query",
            {
                "rewritten": new_query != current,
                "normalized_after_retry": True,
                "normalization_source": str(normalized_meta.get("source") or ""),
                "hyde_regenerated": bool(hyde_docs),
                "hyde_docs_count": len(hyde_docs),
                "hyde_reason": hyde_reason,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


def route_after_doc_grader(state: dict, settings: Settings) -> str:
    """Route after DocGrader: generate vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    reflection = state.get("reflection")
    passed = (
        reflection.get("relevance_passed") if isinstance(reflection, dict) else None
    )
    if passed is True:
        return "generate"
    loop_counts = _get_loop_counts(state)
    if loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
        return "force_exit"
    return "transform_query"


def route_after_answer_review(state: dict, settings: Settings) -> str:
    """Route after AnswerReview: finalize vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return "force_exit"

    reflection = state.get("reflection")
    passed = reflection.get("review_passed") if isinstance(reflection, dict) else None
    if passed is True:
        return "finalize"

    reason = _as_str(reflection.get("reason")) if isinstance(reflection, dict) else ""
    if reason in _CITATION_ONLY_FAILURE_REASONS:
        if loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
            return "force_exit"
        return "transform_query"

    if loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
        return "force_exit"
    return "transform_query"


def finalize_answer(state: dict) -> dict[str, Any]:
    """Emit final answer as an AIMessage (stream-visible)."""
    final_answer = _as_str(
        state.get("draft_answer") or state.get("final_answer")
    ).strip()
    if not final_answer:
        final_answer = "根据现有资料无法回答该问题（未生成答案）。"
    return {
        "final_answer": final_answer,
        "messages": [AIMessage(content=final_answer)],
    }
