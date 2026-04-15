"""KB Chat answer subgraph 审查节点。"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from app.agents.kb_chat_agentic.reflection import _build_answer_coverage_hint
from app.agents.kb_chat_agentic.schemas import AnswerReviewSubDecision
from app.agents.kb_chat_agentic_state import (
    AnswerReviewCitationInput,
    AnswerReviewDispatchInput,
    AnswerReviewFuseInput,
    AnswerReviewInput,
)
from app.core.settings import Settings
from app.prompts import get_prompt_loader

from .answer_subgraph_review_helpers import (
    _coalesce_paragraph_summary,
    _detect_multi_entity_answer_gap,
    _detect_required_original_term_gap,
    _is_repairable_review_failure,
    _judge_structured,
    _resolve_answer_review_details,
    _resolve_subcheck,
    _review_paragraph_citations,
)
from .answer_subgraph_shared import (
    KbChatAnswerSubgraphContext,
    _REVIEW_CHECKS,
    _as_str,
    _current_review_round,
    _format_paragraph_review_payload,
    _get_loop_counts,
    _load_answer_paragraphs,
    _merge_stage_summary,
    _merge_subgraph_state,
    _resolve_allowed_citation_labels,
    _resolve_query_text,
)
from .budget import now_iso


async def _answer_review_dispatch(
    state: AnswerReviewDispatchInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> Command[str]:
    _ = runtime, settings
    review_round = _current_review_round(state)
    send_tasks: list[Send] = [
        Send(
            "answer_review_citation",
            {
                **state,
                "answer_review_task": {
                    "check": "citation",
                    "review_round": review_round,
                },
            },
        ),
        Send(
            "answer_review",
            {
                **state,
                "answer_review_task": {
                    "check": "answer",
                    "review_round": review_round,
                },
            },
        ),
    ]
    return Command(
        update={
            **_merge_subgraph_state(
                state,
                {"phase": "answer_review_dispatch", "last_updated_at": now_iso()},
            ),
            **_merge_stage_summary(
                state,
                "answer_review_dispatch",
                {
                    "review_round": review_round,
                    "check_count": len(send_tasks),
                    "checks": list(_REVIEW_CHECKS),
                    "latency_ms": 0,
                    "completed_at": now_iso(),
                },
            ),
        },
        goto=send_tasks,
    )


def _emit_review_event(payload: dict[str, Any]) -> None:
    writer = None
    try:
        writer = get_stream_writer()
    except Exception:
        writer = None
    if callable(writer):
        writer(payload)


async def _answer_review_citation(
    state: AnswerReviewCitationInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel | None = None,
) -> dict[str, Any]:
    _ = settings
    start = time.perf_counter()
    review_round = _current_review_round(state)
    draft = _as_str(state.get("draft_answer")).strip()
    raw_final_context = _as_str(state.get("final_context")).strip()
    question = _resolve_query_text(state)
    evidence_labels, label_source, final_context = _resolve_allowed_citation_labels(
        state,
        final_context=raw_final_context,
    )
    paragraphs = _load_answer_paragraphs(state, draft_answer=draft)
    paragraph_review = _review_paragraph_citations(
        paragraphs,
        allowed_labels=evidence_labels,
    )
    all_citations = (
        paragraph_review["all_citations"]
        if isinstance(paragraph_review["all_citations"], list)
        else []
    )
    valid_citations = (
        paragraph_review["valid_citations"]
        if isinstance(paragraph_review["valid_citations"], set)
        else set()
    )
    invalid_citations = (
        paragraph_review["invalid_citations"]
        if isinstance(paragraph_review["invalid_citations"], set)
        else set()
    )
    missing_citations = (
        paragraph_review["missing_citations"]
        if isinstance(paragraph_review["missing_citations"], list)
        else []
    )
    citation_mismatches = (
        paragraph_review["citation_mismatches"]
        if isinstance(paragraph_review["citation_mismatches"], list)
        else []
    )
    affected_paragraph_ids = (
        paragraph_review["affected_paragraph_ids"]
        if isinstance(paragraph_review["affected_paragraph_ids"], list)
        else []
    )
    details = (
        paragraph_review["details"]
        if isinstance(paragraph_review["details"], dict)
        else {}
    )
    fallback_reason: str | None = None
    decision_source = "rule"
    if not draft:
        passed = False
        reason = "non_answer"
        confidence = 0.9
    elif not evidence_labels:
        passed = False
        reason = "no_evidence"
        confidence = 0.9
    elif isinstance(state.get("answer_paragraphs"), list) and not paragraphs:
        passed = True
        reason = "passed"
        confidence = 1.0
        missing_citations = []
    elif paragraph_review["reason"] != "passed":
        passed = bool(paragraph_review["passed"])
        reason = _as_str(paragraph_review["reason"]).strip() or "missing_citations"
        confidence = 0.9
        if reason == "citation_mismatch":
            missing_citations = citation_mismatches
    elif bool(paragraph_review["needs_llm"]):
        review_model = chat_model or getattr(runtime, "chat_model", None)
        prompts = get_prompt_loader()
        try:
            system_prompt = prompts.render_with_few_shot("kb_chat/citation_review")
        except KeyError:
            system_prompt = (
                "你是严格的知识库段落级引用来源审查器。"
                "请基于段落、claim 与 citation_ids 判断主断言的来源是否完整且对齐。"
                '仅输出 JSON：{"passed": true/false, "reason": "passed|missing_citations|citation_mismatch", "confidence": 0-1, "missing_citations": [], "unsupported_claims": [], "affected_paragraph_ids": [], "details": {}}。'
            )
        if review_model is None:
            judge = None
            fallback_reason = "missing_chat_model"
        else:
            judge, fallback_reason = await _judge_structured(
                chat_model=review_model,
                system=system_prompt,
                user=(
                    f"问题：{question}\n\n"
                    f"参考内容：\n{final_context}\n\n"
                    f"回答：\n{draft}\n\n"
                    "段落级审查数据：\n"
                    f"{_format_paragraph_review_payload(paragraphs)}"
                ),
            )
        if isinstance(judge, AnswerReviewSubDecision):
            passed = bool(judge.passed)
            reason = judge.reason
            confidence = max(0.0, min(1.0, float(judge.confidence)))
            decision_source = "llm"
            judge_missing_citations = (
                judge.missing_citations
                if isinstance(judge.missing_citations, list)
                else missing_citations
            )
            missing_citations = [] if passed else list(judge_missing_citations)
            judge_affected_ids = (
                judge.affected_paragraph_ids
                if isinstance(judge.affected_paragraph_ids, list)
                else affected_paragraph_ids
            )
            affected_paragraph_ids = list(judge_affected_ids)
            if isinstance(judge.details, dict) and judge.details:
                details = dict(judge.details)
        else:
            passed = (
                _as_str(getattr(settings, "kb_chat_grader_fail_policy", "closed"))
                .strip()
                .lower()
                == "open"
            )
            reason = "passed" if passed else "missing_citations"
            confidence = 0.0
            decision_source = "fallback"
            missing_citations = [] if passed else missing_citations
    else:
        passed = True
        reason = "passed"
        confidence = 1.0
        missing_citations = []
    result = {
        "review_round": review_round,
        "check": "citation",
        "passed": passed,
        "reason": reason,
        "confidence": confidence,
        "details": details,
        "affected_paragraph_ids": affected_paragraph_ids,
        "fallback_reason": fallback_reason,
        "decision_source": decision_source,
        "label_source": label_source,
        "citation_count": len(all_citations),
        "valid_citation_count": len(valid_citations),
        "available_citation_labels": sorted(evidence_labels.values()),
        "invalid_citations": sorted(invalid_citations),
        "missing_citations": missing_citations,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }
    _emit_review_event(
        {
            "event_type": "answer_review_subcheck",
            "check": "citation",
            "passed": passed,
            "reason": reason,
            "ts": now_iso(),
        }
    )
    return {"answer_review_runs": [result]}


async def _answer_review_llm_check(
    state: AnswerReviewInput,
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    start = time.perf_counter()
    review_round = _current_review_round(state)
    question = _resolve_query_text(state)
    raw_final_context = _as_str(state.get("final_context")).strip()
    _, _, final_context = _resolve_allowed_citation_labels(
        state,
        final_context=raw_final_context,
    )
    draft = _as_str(state.get("draft_answer")).strip()
    paragraphs = _load_answer_paragraphs(state, draft_answer=draft)
    fallback_reason: str | None = None
    prompt_key = "kb_chat/answer_review"
    default_system = (
        "你是严格的知识库答案有效性审查器。"
        "请同时判断回答是否直接回应问题，以及主断言与辅助断言分别是否被参考内容支持。"
        '仅输出 JSON：{"passed": true/false, "reason": "...", "confidence": 0-1, "missing_citations": [], "unsupported_claims": [], "affected_paragraph_ids": [], "details": {}}。'
    )
    prompts = get_prompt_loader()
    try:
        system_prompt = prompts.render_with_few_shot(prompt_key)
    except KeyError:
        system_prompt = default_system
    coverage_hint = _build_answer_coverage_hint(question, final_context)
    coverage_block = f"{coverage_hint}\n\n" if coverage_hint else ""
    judge, fallback_reason = await _judge_structured(
        chat_model=chat_model,
        system=system_prompt,
        user=(
            f"问题：{question}\n\n"
            f"{coverage_block}"
            f"参考内容：\n{final_context}"
            f"\n\n回答：\n{draft}\n\n段落级审查数据：\n{_format_paragraph_review_payload(paragraphs)}"
        ),
    )
    if isinstance(judge, AnswerReviewSubDecision):
        passed = bool(judge.passed)
        reason = judge.reason
        confidence = float(judge.confidence)
        decision_source = "llm"
        unsupported_claims = list(judge.unsupported_claims)
        missing_citations = list(judge.missing_citations)
    else:
        passed = settings.kb_chat_grader_fail_policy == "open"
        reason = "fallback_open" if passed else "fallback_closed"
        confidence = 0.0
        decision_source = "fallback"
        unsupported_claims = []
        missing_citations = []
    coverage_gap = _detect_multi_entity_answer_gap(
        question=question,
        draft=draft,
        paragraphs=paragraphs,
    )
    if coverage_gap is None:
        coverage_gap = _detect_required_original_term_gap(
            question=question,
            draft=draft,
            paragraphs=paragraphs,
            final_context=final_context,
        )
    if passed and coverage_gap is not None:
        passed = False
        reason = str(coverage_gap.get("reason") or "incomplete")
        confidence = min(confidence, 0.35)
        decision_source = "deterministic_guard"
    affected_paragraph_ids, details = _resolve_answer_review_details(
        paragraphs,
        reason=reason,
        unsupported_claims=unsupported_claims,
    )
    if coverage_gap is not None:
        repair_target_count_raw = coverage_gap.get("repair_target_count")
        guard_details = {
            "coverage_guardrail": coverage_gap.get("coverage_guardrail"),
            "missing_entities": coverage_gap.get("missing_entities") or [],
            "missing_terms": coverage_gap.get("missing_terms") or {},
            "required_dimensions": coverage_gap.get("required_dimensions") or [],
            "repair_target_count": (
                int(repair_target_count_raw)
                if isinstance(repair_target_count_raw, (int, float))
                else 0
            ),
        }
        details = {
            **details,
            **guard_details,
        }
        guard_affected_ids = coverage_gap.get("affected_paragraph_ids")
        if (
            isinstance(guard_affected_ids, list)
            and guard_affected_ids
            and not affected_paragraph_ids
        ):
            affected_paragraph_ids = [
                _as_str(paragraph_id).strip()
                for paragraph_id in guard_affected_ids
                if _as_str(paragraph_id).strip()
            ]
    if isinstance(judge, AnswerReviewSubDecision):
        if judge.affected_paragraph_ids:
            affected_paragraph_ids = list(judge.affected_paragraph_ids)
        judge_details = judge.details if isinstance(judge.details, dict) else None
        if judge_details:
            details = {**details, **judge_details}
    result = {
        "review_round": review_round,
        "check": "answer",
        "passed": passed,
        "reason": reason,
        "confidence": max(0.0, min(1.0, confidence)),
        "unsupported_claims": unsupported_claims,
        "missing_citations": missing_citations,
        "affected_paragraph_ids": affected_paragraph_ids,
        "details": details,
        "fallback_reason": fallback_reason,
        "decision_source": decision_source,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }
    _emit_review_event(
        {
            "event_type": "answer_review_subcheck",
            "check": "answer",
            "passed": passed,
            "reason": reason,
            "fallback_reason": fallback_reason,
            "ts": now_iso(),
        }
    )
    return {"answer_review_runs": [result]}


async def _answer_review(
    state: AnswerReviewInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    return await _answer_review_llm_check(
        state, settings=settings, chat_model=chat_model
    )


async def _answer_review_fuse(
    state: AnswerReviewFuseInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> Command[str]:
    _ = runtime
    start = time.perf_counter()
    review_round = _current_review_round(state)
    loop_counts = _get_loop_counts(state)
    loop_counts_updates = {**loop_counts}
    by_check = {
        check: (
            _resolve_subcheck(state, check)
            or {
                "review_round": review_round,
                "check": check,
                "passed": False,
                "reason": "fallback_closed",
            }
        )
        for check in _REVIEW_CHECKS
    }
    citation = by_check["citation"]
    answer = by_check["answer"]
    checks = [citation, answer]
    passed = all(bool(item.get("passed")) for item in checks)
    reason = "passed"
    if not passed:
        for key in ("citation", "answer"):
            current = by_check[key]
            if not bool(current.get("passed")):
                reason = _as_str(current.get("reason")).strip() or "fallback_closed"
                break
    avg_confidence = sum(float(item.get("confidence") or 0.0) for item in checks) / max(
        1, len(checks)
    )
    fallback_reason = next(
        (
            _as_str(item.get("fallback_reason")).strip()
            for item in checks
            if _as_str(item.get("fallback_reason")).strip()
        ),
        None,
    )
    decision_sources = {
        _as_str(item.get("decision_source")).strip()
        for item in checks
        if _as_str(item.get("decision_source")).strip()
    }
    if not passed:
        review_risk_level = "high"
    elif avg_confidence >= 0.8:
        review_risk_level = "low"
    else:
        review_risk_level = "medium"
    action = "none" if passed else "transform_query"
    draft = _as_str(state.get("draft_answer")).strip()
    paragraph_review_counts, repair_target_count, unsupported_scope_summary = (
        _coalesce_paragraph_summary(citation, answer)
    )
    best_answer_meta: dict[str, Any] | None = None
    if passed and draft:
        best_answer_meta = {
            "from_node": "answer_review_fuse",
            "reason": reason,
            "retrieval_round": max(loop_counts.get("retrieval_retries", 0), 0),
            "total_rounds": loop_counts_updates.get("total_rounds", 0),
            "completed_at": now_iso(),
        }
    stage_summary = {
        "review_round": review_round,
        "passed": passed,
        "reason": reason,
        "fallback_reason": fallback_reason,
        "fallback_used": fallback_reason is not None,
        "review_breakdown": by_check,
        "review_risk_level": review_risk_level,
        "review_confidence": round(max(0.0, min(1.0, avg_confidence)), 4),
        "review_decision_source": "mixed"
        if len(decision_sources) > 1
        else (next(iter(decision_sources)) if decision_sources else "unknown"),
        "paragraph_review_counts": paragraph_review_counts,
        "paragraph_pass_count": int(paragraph_review_counts.get("passed") or 0),
        "repair_target_count": repair_target_count,
        "unsupported_scope_summary": unsupported_scope_summary,
        "best_answer": draft if passed and draft else None,
        "best_answer_meta": best_answer_meta,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "completed_at": now_iso(),
    }
    reflection = state.get("reflection")
    reflection_update = reflection if isinstance(reflection, dict) else {}
    updates: dict[str, Any] = {
        "loop_counts": loop_counts_updates,
        "reflection": {
            **reflection_update,
            "review_passed": passed,
            "action": action,
            "reason": reason,
            "review_breakdown": by_check,
            "review_risk_level": review_risk_level,
            "review_confidence": stage_summary["review_confidence"],
            "review_decision_source": stage_summary["review_decision_source"],
        },
    }
    updates = {
        **updates,
        **_merge_stage_summary(state, "answer_review", stage_summary, updates=updates),
    }
    updates = {
        **updates,
        **_merge_stage_summary(
            state, "answer_review_fuse", stage_summary, updates=updates
        ),
    }
    updates = {
        **updates,
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_review_fuse",
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }
    goto = "answer_commit" if passed else "answer_repair"
    generation_retries = int(loop_counts.get("generation_retries") or 0)
    max_generation_retries = int(settings.kb_chat_max_generation_retries)
    if (
        not passed
        and _is_repairable_review_failure(
            reason=_as_str(reason),
            citation=citation,
            answer=answer,
        )
        and generation_retries >= max_generation_retries
    ):
        goto = "answer_commit"
    elif not passed and not _is_repairable_review_failure(
        reason=_as_str(reason),
        citation=citation,
        answer=answer,
    ):
        goto = "answer_commit"
    _emit_review_event(
        {
            "event_type": "answer_review_fused",
            "passed": passed,
            "reason": reason,
            "goto": goto,
            "risk_level": review_risk_level,
            "fallback_reason": fallback_reason,
            "ts": now_iso(),
        }
    )
    return Command(update=updates, goto=goto)


