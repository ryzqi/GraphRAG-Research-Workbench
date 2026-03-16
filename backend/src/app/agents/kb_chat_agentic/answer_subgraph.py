"""KB Chat answer generation subgraph.

This subgraph encapsulates draft generation -> review -> optional repair ->
commit. It keeps the parent graph routing contract intact by writing
`reflection.action/reason` and `stage_summaries.answer_subgraph`.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Literal, TypedDict

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy, Send
from pydantic import ValidationError

from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.agents.kb_chat_agentic.reflection import generate_draft
from app.agents.kb_chat_agentic.schemas import AnswerReviewSubDecision
from app.agents.kb_chat_agentic_state import (
    AnswerCommitInput,
    AnswerRepairInput,
    AnswerReviewCitationInput,
    AnswerReviewDispatchInput,
    AnswerReviewFuseInput,
    AnswerReviewLLMInput,
    ChainOfVerificationInput,
    ClaimCitationCheckInput,
    CoveCheckInput,
    DraftGenerateInput,
    KbChatInternalState,
    merge_routing_decision,
)
from app.core.settings import Settings
from app.prompts import get_prompt_loader
from app.services.evidence_guardrails import resolve_kb_refusal_answer
from app.services.streaming import extract_answer_text

from .budget import now_iso

_REPAIRABLE_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
}
_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
_EVIDENCE_BLOCK_RE = re.compile(
    r"^\[([^\[\]\n]{1,128})\]\s*(.*?)(?=^\[[^\[\]\n]{1,128}\]\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,128})\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")
_REVIEW_CHECKS: tuple[Literal["citation", "factual", "answerability"], ...] = (
    "citation",
    "factual",
    "answerability",
)
_HIGH_RISK_HINTS: tuple[str, ...] = (
    "安全",
    "法律",
    "合规",
    "医疗",
    "药",
    "财务",
    "合同",
    "赔偿",
    "处罚",
)


class KbChatAnswerSubgraphContext(TypedDict, total=False):
    """Typed runtime context propagated from parent graph."""

    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _get_loop_counts(state: dict[str, Any]) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _current_review_round(state: dict[str, Any]) -> int:
    loop_counts = _get_loop_counts(state)
    return max(int(loop_counts.get("generation_retries") or 0), 0)


def _resolve_answer_subgraph_next_step(
    state: AnswerCommitInput,
    *,
    settings: Settings,
) -> str:
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    if reflection_obj.get("review_passed") is True:
        return "confidence_calibrate"

    loop_counts = _get_loop_counts(state)
    max_total_rounds = int(getattr(settings, "kb_chat_max_total_rounds", 3))
    max_retrieval_retries = int(getattr(settings, "kb_chat_max_retrieval_retries", 2))
    if loop_counts["total_rounds"] >= max_total_rounds:
        return "force_exit"
    if loop_counts["retrieval_retries"] >= max_retrieval_retries:
        return "force_exit"
    return "transform_query"


def _merge_stage_summary(
    state: dict[str, Any],
    key: str,
    summary: dict[str, Any],
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {}
    state_stage = state.get("stage_summaries")
    if isinstance(state_stage, dict):
        base = {**state_stage}
    if isinstance(updates, dict):
        updates_stage = updates.get("stage_summaries")
        if isinstance(updates_stage, dict):
            base = {**base, **updates_stage}
    return {"stage_summaries": {**base, key: summary}}


def _merge_subgraph_state(
    state: dict[str, Any],
    patch: dict[str, Any],
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    current = state.get("answer_subgraph_state")
    if isinstance(current, dict):
        merged = {**current}
    if isinstance(updates, dict):
        in_updates = updates.get("answer_subgraph_state")
        if isinstance(in_updates, dict):
            merged = {**merged, **in_updates}
    return {"answer_subgraph_state": {**merged, **patch}}


def _resolve_query_text(state: dict[str, Any]) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


def _extract_evidence_labels(final_context: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not final_context:
        return labels
    for match in _EVIDENCE_LINE_RE.finditer(final_context):
        raw = _as_str(match.group(1)).strip()
        if not raw:
            continue
        normalized = f"[{raw}]"
        labels.setdefault(normalized.casefold(), normalized)
    return labels


def _extract_citations(answer: str) -> list[str]:
    if not answer:
        return []
    return [f"[{match.group(1).strip()}]" for match in _CITATION_RE.finditer(answer)]


def _strip_citations(text: str) -> str:
    return _CITATION_RE.sub("", text or "").strip()


def _extract_terms(text: str) -> set[str]:
    cleaned = _strip_citations(text)
    english = {
        match.group(0).lower()
        for match in re.finditer(r"[A-Za-z0-9_]{2,}", cleaned)
    }
    chinese_chars = [char for char in cleaned if "\u4e00" <= char <= "\u9fff"]
    grams: set[str] = set()
    for size in (2, 3):
        for index in range(0, max(len(chinese_chars) - size + 1, 0)):
            grams.add("".join(chinese_chars[index : index + size]))
    return {token for token in {*english, *grams} if token}


def _split_claims(answer: str) -> list[str]:
    segments = [
        segment.strip()
        for segment in _SENTENCE_SPLIT_RE.split(answer or "")
        if isinstance(segment, str) and segment.strip()
    ]
    if segments:
        merged_segments: list[str] = []
        for segment in segments:
            citations = _extract_citations(segment)
            leading_citations: list[str] = []
            remainder = segment
            for citation in citations:
                if remainder.startswith(citation):
                    leading_citations.append(citation)
                    remainder = remainder[len(citation) :].lstrip()
                else:
                    break
            if leading_citations and merged_segments:
                merged_segments[-1] = f"{merged_segments[-1]}{''.join(leading_citations)}"
            if remainder:
                merged_segments.append(remainder)
        return merged_segments
    normalized = (answer or "").strip()
    return [normalized] if normalized else []


def _parse_evidence_blocks(final_context: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in _EVIDENCE_BLOCK_RE.finditer(final_context or ""):
        label = _as_str(match.group(1)).strip()
        body = _as_str(match.group(2)).strip()
        if not label or not body:
            continue
        blocks[f"[{label}]"] = body
    return blocks


def _claim_support_metrics(claim: str, evidence_text: str) -> tuple[int, float]:
    claim_terms = _extract_terms(claim)
    evidence_terms = _extract_terms(evidence_text)
    if not claim_terms or not evidence_terms:
        return 0, 0.0
    overlap = len(claim_terms & evidence_terms)
    ratio = overlap / max(len(claim_terms), 1)
    return overlap, ratio


def _claim_is_supported(claim: str, evidence_text: str) -> bool:
    overlap, ratio = _claim_support_metrics(claim, evidence_text)
    return overlap >= 2 and ratio >= 0.15


def _best_matching_label(claim: str, evidence_blocks: dict[str, str]) -> str | None:
    best_label: str | None = None
    best_overlap = 0
    best_ratio = 0.0
    for label, evidence_text in evidence_blocks.items():
        overlap, ratio = _claim_support_metrics(claim, evidence_text)
        if overlap > best_overlap or (overlap == best_overlap and ratio > best_ratio):
            best_label = label
            best_overlap = overlap
            best_ratio = ratio
    if best_label is None:
        return None
    return best_label if best_overlap >= 2 and best_ratio >= 0.15 else None


def _attach_citation_to_claim(claim: str, citation: str) -> str:
    stripped = _strip_citations(claim).strip()
    if not stripped:
        return citation
    if stripped.endswith(("。", "！", "？", ";", "；", ".", "!", "?")):
        return f"{stripped[:-1]}{citation}{stripped[-1]}"
    return f"{stripped}{citation}"


def _partition_citations(
    answer: str, *, allowed_labels: dict[str, str]
) -> tuple[list[str], set[str], set[str]]:
    if not answer:
        return [], set(), set()
    all_citations = _extract_citations(answer)
    valid: set[str] = set()
    invalid: set[str] = set()
    for label in all_citations:
        key = label.casefold()
        if key in allowed_labels:
            valid.add(allowed_labels[key])
        else:
            invalid.add(label)
    return all_citations, valid, invalid


def _classify_structured_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "StructuredOutputValidationError":
        return "invalid_schema"
    if name == "MultipleStructuredOutputsError":
        return "multiple_structured_outputs"
    return "error"


async def _judge_structured(
    *,
    chat_model: BaseChatModel,
    system: str,
    user: str,
) -> tuple[AnswerReviewSubDecision | None, str | None]:
    agent = create_agent(
        model=chat_model,
        tools=[],
        system_prompt=system,
        response_format=AnswerReviewSubDecision,
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
    if isinstance(structured_payload, AnswerReviewSubDecision):
        return structured_payload, None
    try:
        payload = AnswerReviewSubDecision.model_validate(structured_payload)
    except ValidationError:
        return None, "invalid_schema"
    return payload, None


def _resolve_subcheck(
    state: AnswerReviewFuseInput,
    check: str,
) -> dict[str, Any] | None:
    active_round = _current_review_round(state)
    runs = state.get("answer_review_runs")
    if not isinstance(runs, list):
        return None
    for run in reversed(runs):
        if not isinstance(run, dict):
            continue
        if _as_str(run.get("check")) != check:
            continue
        run_round = run.get("review_round")
        if isinstance(run_round, int):
            if run_round == active_round:
                return run
            continue
        if active_round == 0:
            return run
    return None


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
            "answer_review_factual",
            {
                **state,
                "answer_review_task": {
                    "check": "factual",
                    "review_round": review_round,
                },
            },
        ),
        Send(
            "answer_review_answerability",
            {
                **state,
                "answer_review_task": {
                    "check": "answerability",
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
) -> dict[str, Any]:
    _ = runtime, settings
    start = time.perf_counter()
    review_round = _current_review_round(state)
    draft = _as_str(state.get("draft_answer")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    evidence_labels = _extract_evidence_labels(final_context)
    all_citations, valid_citations, invalid_citations = _partition_citations(
        draft, allowed_labels=evidence_labels
    )
    if not draft:
        passed = False
        reason = "non_answer"
    elif not evidence_labels:
        passed = False
        reason = "no_evidence"
    elif not all_citations:
        passed = False
        reason = "missing_citations"
    elif invalid_citations:
        passed = False
        reason = "invalid_citations"
    else:
        passed = True
        reason = "passed"
    result = {
        "review_round": review_round,
        "check": "citation",
        "passed": passed,
        "reason": reason,
        "confidence": 1.0 if passed else 0.9,
        "fallback_reason": None,
        "decision_source": "rule",
        "citation_count": len(all_citations),
        "valid_citation_count": len(valid_citations),
        "invalid_citations": sorted(invalid_citations),
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
    state: AnswerReviewLLMInput,
    *,
    settings: Settings,
    chat_model: BaseChatModel,
    check: Literal["factual", "answerability"],
) -> dict[str, Any]:
    start = time.perf_counter()
    review_round = _current_review_round(state)
    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    draft = _as_str(state.get("draft_answer")).strip()
    fallback_reason: str | None = None
    if check == "factual":
        prompt_key = "kb_chat/answer_review"
        default_system = (
            "你是严格的知识库回答事实审查器。"
            "仅判断回答是否被参考内容支持，重点检查无依据断言和引用一致性。"
            '仅输出 JSON：{"passed": true/false, "reason": "...", "confidence": 0-1}。'
        )
    else:
        prompt_key = "kb_chat/answer_review"
        default_system = (
            "你是严格的知识库回答有效性审查器。"
            "仅判断回答是否直接回答问题，避免答非所问、空泛套话。"
            '仅输出 JSON：{"passed": true/false, "reason": "...", "confidence": 0-1}。'
        )
    prompts = get_prompt_loader()
    try:
        system_prompt = prompts.render_with_few_shot(prompt_key)
    except KeyError:
        system_prompt = default_system
    judge, fallback_reason = await _judge_structured(
        chat_model=chat_model,
        system=system_prompt,
        user=(
            f"问题：{question}\n\n参考内容：\n{final_context[:4000]}"
            f"\n\n回答：\n{draft[:2000]}"
        ),
    )
    if isinstance(judge, AnswerReviewSubDecision):
        passed = bool(judge.passed)
        reason = judge.reason
        confidence = float(judge.confidence)
        decision_source = "llm"
    else:
        passed = settings.kb_chat_grader_fail_policy == "open"
        reason = "fallback_open" if passed else "fallback_closed"
        confidence = 0.0
        decision_source = "fallback"
    result = {
        "review_round": review_round,
        "check": check,
        "passed": passed,
        "reason": reason,
        "confidence": max(0.0, min(1.0, confidence)),
        "fallback_reason": fallback_reason,
        "decision_source": decision_source,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }
    _emit_review_event(
        {
            "event_type": "answer_review_subcheck",
            "check": check,
            "passed": passed,
            "reason": reason,
            "fallback_reason": fallback_reason,
            "ts": now_iso(),
        }
    )
    return {"answer_review_runs": [result]}


async def _answer_review_factual(
    state: AnswerReviewLLMInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    return await _answer_review_llm_check(
        state, settings=settings, chat_model=chat_model, check="factual"
    )


async def _answer_review_answerability(
    state: AnswerReviewLLMInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    return await _answer_review_llm_check(
        state, settings=settings, chat_model=chat_model, check="answerability"
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
    factual = by_check["factual"]
    answerability = by_check["answerability"]
    checks = [citation, factual, answerability]
    passed = all(bool(item.get("passed")) for item in checks)
    reason = "passed"
    if not passed:
        for key in ("citation", "factual", "answerability"):
            current = by_check[key]
            if not bool(current.get("passed")):
                reason = _as_str(current.get("reason")).strip() or "fallback_closed"
                break
    avg_confidence = sum(float(item.get("confidence") or 0.0) for item in checks) / max(1, len(checks))
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
        "review_decision_source": "mixed" if len(decision_sources) > 1 else (next(iter(decision_sources)) if decision_sources else "unknown"),
        "best_answer": draft if passed and draft else None,
        "best_answer_meta": best_answer_meta,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "completed_at": now_iso(),
    }
    updates: dict[str, Any] = {
        "loop_counts": loop_counts_updates,
        "reflection": {
            **(state.get("reflection") if isinstance(state.get("reflection"), dict) else {}),
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
        **_merge_stage_summary(state, "answer_review_fuse", stage_summary, updates=updates),
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
    goto = "cove_check" if passed else "answer_repair"
    generation_retries = int(loop_counts.get("generation_retries") or 0)
    max_generation_retries = int(settings.kb_chat_max_generation_retries)
    if (
        not passed
        and _as_str(reason) in _REPAIRABLE_FAILURE_REASONS
        and generation_retries >= max_generation_retries
    ):
        goto = "answer_commit"
    elif not passed and _as_str(reason) not in _REPAIRABLE_FAILURE_REASONS:
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


def _is_high_risk_query(state: CoveCheckInput) -> bool:
    query = _resolve_query_text(state)
    lowered = query.lower()
    return any(hint in query for hint in _HIGH_RISK_HINTS) or "risk" in lowered


def _cove_check(state: CoveCheckInput) -> Command[str]:
    high_risk = _is_high_risk_query(state)
    stage = _merge_stage_summary(
        state,
        "cove_check",
        {
            "high_risk": high_risk,
            "enabled": high_risk,
            "completed_at": now_iso(),
        },
    )
    updates = {
        "cove_state": {
            "enabled": high_risk,
            "triggered": high_risk,
            "passed": None,
            "reason": "pending" if high_risk else "skipped_low_risk",
        },
        **stage,
    }
    return Command(
        update=updates,
        goto="chain_of_verification" if high_risk else "claim_citation_check",
    )


def _chain_of_verification(state: ChainOfVerificationInput) -> dict[str, Any]:
    draft = _as_str(state.get("draft_answer")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    evidence_blocks = _parse_evidence_blocks(final_context)
    claims = _split_claims(draft)
    supported_claims: list[str] = []
    unsupported_claims: list[str] = []
    claim_reports: list[dict[str, Any]] = []
    for claim in claims:
        cited_labels = [
            label for label in _extract_citations(claim) if label in evidence_blocks
        ]
        supported = False
        if cited_labels:
            supported = any(
                _claim_is_supported(claim, evidence_blocks[label])
                for label in cited_labels
            )
        else:
            matched_label = _best_matching_label(claim, evidence_blocks)
            supported = matched_label is not None
        if supported:
            supported_claims.append(claim)
        else:
            unsupported_claims.append(claim)
        claim_reports.append(
            {
                "claim": claim,
                "citations": _extract_citations(claim),
                "supported": supported,
            }
        )

    revised_answer = " ".join(supported_claims).strip()
    revised_claim_count = max(len(claims) - len(supported_claims), 0)
    passed = bool(revised_answer) if claims else bool(draft and final_context)
    reason = (
        "passed"
        if revised_claim_count == 0 and passed
        else "revised_claims"
        if passed
        else "insufficient_verification_signal"
    )
    stage = _merge_stage_summary(
        state,
        "chain_of_verification",
        {
            "passed": passed,
            "reason": reason,
            "claim_count": len(claims),
            "supported_claim_count": len(supported_claims),
            "revised_claim_count": revised_claim_count,
            "unsupported_claims": unsupported_claims[:6],
            "claim_reports": claim_reports[:12],
            "completed_at": now_iso(),
        },
    )
    return {
        "draft_answer": revised_answer or draft,
        "cove_state": {
            "enabled": True,
            "triggered": True,
            "passed": passed,
            "reason": reason,
            "claim_count": len(claims),
            "supported_claim_count": len(supported_claims),
            "revised_claim_count": revised_claim_count,
            "supported_ratio": round(
                len(supported_claims) / max(len(claims), 1),
                4,
            )
            if claims
            else 1.0,
        },
        **stage,
    }


def _claim_citation_check(state: ClaimCitationCheckInput) -> Command[str]:
    draft = _as_str(state.get("draft_answer")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    labels = _extract_evidence_labels(final_context)
    evidence_blocks = _parse_evidence_blocks(final_context)
    claims = _split_claims(draft)
    repaired_claims: list[str] = []
    repair_suggestions: list[str] = []
    unaligned_claims: list[str] = []
    aligned_count = 0
    for claim in claims:
        citations = _extract_citations(claim)
        valid_claim_citations = [
            label for label in citations if label.casefold() in labels
        ]
        best_label = _best_matching_label(claim, evidence_blocks)
        aligned = False
        next_claim = claim
        if valid_claim_citations:
            aligned = any(
                _claim_is_supported(
                    claim,
                    evidence_blocks.get(labels[label.casefold()], ""),
                )
                for label in valid_claim_citations
            )
        if not aligned and best_label is not None:
            next_claim = _attach_citation_to_claim(claim, best_label)
            aligned = True
            if citations:
                repair_suggestions.append(f"replace:{claim}->{best_label}")
            else:
                repair_suggestions.append(f"append:{claim}->{best_label}")
        if aligned:
            aligned_count += 1
            repaired_claims.append(next_claim)
        else:
            unaligned_claims.append(_strip_citations(claim))
            repaired_claims.append(_strip_citations(claim))

    repaired_draft = " ".join(claim for claim in repaired_claims if claim.strip()).strip()
    _, valid_citations, invalid_citations = _partition_citations(
        repaired_draft, allowed_labels=labels
    )
    cove_state = state.get("cove_state")
    cove_passed = (
        cove_state.get("passed")
        if isinstance(cove_state, dict) and cove_state.get("passed") is not None
        else True
    )
    coverage = (
        round(aligned_count / max(len(claims), 1), 4)
        if claims
        else 1.0
    )
    citation_passed = bool(repaired_draft or draft) and not unaligned_claims and not invalid_citations
    passed = bool(cove_passed) and citation_passed
    reason = "passed"
    if not cove_passed:
        reason = "cove_failed"
    elif unaligned_claims:
        reason = "citation_mismatch"
    elif invalid_citations:
        reason = "invalid_citations"
    elif coverage < 1.0 or not valid_citations:
        reason = "missing_citations"

    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    reflection_patch: dict[str, Any] = {}
    best_answer_updates: dict[str, Any] = {}
    if not passed:
        reflection_patch = {
            "review_passed": False,
            "action": "transform_query",
            "reason": reason,
        }
    elif repaired_draft or draft:
        loop_counts = _get_loop_counts(state)
        best_answer_updates = {
            "best_answer": repaired_draft or draft,
            "best_answer_meta": {
                "from_node": "claim_citation_check",
                "reason": reason,
                "retrieval_round": max(loop_counts.get("retrieval_retries", 0), 0),
                "total_rounds": loop_counts.get("total_rounds", 0),
                "completed_at": now_iso(),
            },
        }

    stage = _merge_stage_summary(
        state,
        "claim_citation_check",
        {
            "passed": passed,
            "reason": reason,
            "coverage": coverage,
            "total_claim_count": len(claims),
            "aligned_claim_count": aligned_count,
            "repair_suggestions": repair_suggestions[:12],
            "unaligned_claims": unaligned_claims[:6],
            "valid_citation_count": len(valid_citations),
            "invalid_citations": sorted(invalid_citations),
            "completed_at": now_iso(),
        },
        updates={"reflection": {**reflection_obj, **reflection_patch}},
    )
    return Command(
        update={
            "draft_answer": repaired_draft or draft,
            **best_answer_updates,
            "cove_state": {
                **(cove_state if isinstance(cove_state, dict) else {}),
                "claim_check_passed": passed,
                "claim_check_reason": reason,
                "claim_coverage": coverage,
            },
            "reflection": {**reflection_obj, **reflection_patch},
            **stage,
        },
        goto="answer_commit" if passed else "answer_repair",
    )


async def _draft_generate(
    state: DraftGenerateInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    updates = await generate_draft(state, settings=settings, chat_model=chat_model)
    return {
        **updates,
        **_merge_subgraph_state(
            state,
            {
                "phase": "draft_generate",
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


async def _answer_repair(
    state: AnswerRepairInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    loop_counts = {
        **loop_counts,
        "generation_retries": loop_counts["generation_retries"] + 1,
    }

    draft_answer = _as_str(state.get("draft_answer")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    question = _resolve_query_text(state)

    repaired_answer = draft_answer
    fallback_reason: str | None = None
    if draft_answer and final_context and question:
        prompts = get_prompt_loader()
        try:
            repair_system = prompts.render_with_few_shot("kb_chat/system")
        except KeyError:
            repair_system = (
                "你是知识库回答修复器。"
                "仅基于参考内容修复回答并补齐有效引用，禁止新增无依据事实。"
            )
        repair_user = (
            "请修复回答，仅输出最终答案正文。\n"
            "要求：\n"
            "1) 仅使用参考内容中的事实；\n"
            "2) 关键事实必须附带有效 [Sx] 引用；\n"
            "3) 不能引入参考内容外信息。\n\n"
            f"问题：{question}\n\n"
            f"参考内容：\n{final_context}\n\n"
            f"原回答：\n{draft_answer}"
        )
        model = chat_model.bind(max_tokens=1024)
        try:
            msg = await model.ainvoke(
                [
                    SystemMessage(content=repair_system),
                    HumanMessage(content=repair_user),
                ]
            )
            candidate = extract_answer_text(getattr(msg, "content", "")).strip()
            if candidate:
                repaired_answer = candidate
            else:
                fallback_reason = "empty_repair_output"
        except asyncio.CancelledError:
            raise
        except Exception:
            fallback_reason = "repair_invoke_failed"
    else:
        fallback_reason = "repair_input_missing"

    subgraph_state = state.get("answer_subgraph_state")
    repair_attempts = (
        int(subgraph_state.get("repair_attempts") or 0)
        if isinstance(subgraph_state, dict)
        else 0
    ) + 1
    updates: dict[str, Any] = {
        "loop_counts": loop_counts,
        "draft_answer": repaired_answer,
        "final_answer": repaired_answer,
    }
    updates = {
        **updates,
        **_merge_stage_summary(
            state,
            "answer_repair",
            {
                "repair_attempt": repair_attempts,
                "fallback_reason": fallback_reason,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
            updates=updates,
        ),
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_repair",
                "repair_attempts": repair_attempts,
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }
    return updates


async def _answer_commit(
    state: AnswerCommitInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> dict[str, Any]:
    _ = runtime
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    loop_counts = _get_loop_counts(state)
    repair_attempts = 0
    subgraph_state = state.get("answer_subgraph_state")
    if isinstance(subgraph_state, dict):
        repair_attempts = int(subgraph_state.get("repair_attempts") or 0)

    next_step = _resolve_answer_subgraph_next_step(state, settings=settings)
    reason = _as_str(reflection_obj.get("reason")).strip().lower()
    review_passed = reflection_obj.get("review_passed") is True
    degrade_reason: str | None = None
    reflection_patch: dict[str, Any] = {}

    if (
        not review_passed
        and loop_counts["generation_retries"]
        >= int(settings.kb_chat_max_generation_retries)
    ):
        next_step = "force_exit"
        degrade_reason = "max_generation_retries"
        reflection_patch = {
            "action": "force_exit",
            "reason": "max_generation_retries",
            "review_passed": False,
        }
    elif next_step == "force_exit":
        degrade_reason = reason or "force_exit"
        reflection_patch = {"action": "force_exit", "reason": degrade_reason}
    elif next_step == "transform_query":
        degrade_reason = reason or "review_failed"
        reflection_patch = {"action": "transform_query", "reason": degrade_reason}
    else:
        reflection_patch = {"action": "none"}

    merged_reflection = {**reflection_obj, **reflection_patch}
    final_answer = _as_str(state.get("final_answer") or state.get("draft_answer")).strip()
    if not final_answer and next_step == "force_exit":
        final_answer = resolve_kb_refusal_answer(reason=degrade_reason or reason)
    best_answer = _as_str(state.get("best_answer")).strip()

    summary = {
        "passed": merged_reflection.get("review_passed") is True,
        "reason": _as_str(merged_reflection.get("reason")).strip(),
        "next_step": next_step,
        "repair_attempts": repair_attempts,
        "generation_retries": loop_counts.get("generation_retries", 0),
        "retrieval_retries": loop_counts.get("retrieval_retries", 0),
        "best_answer": best_answer or None,
        "degrade_reason": degrade_reason,
        "completed_at": now_iso(),
    }

    updates: dict[str, Any] = {
        "reflection": merged_reflection,
        "degrade_reason": degrade_reason,
    }
    updates = {
        **updates,
        **merge_routing_decision(
            state,
            "answer_subgraph",
            {
                "phase": "answer_subgraph",
                "next_node": next_step,
                "action": _as_str(merged_reflection.get("action")).strip() or "none",
                "reason": _as_str(merged_reflection.get("reason")).strip(),
                "reason_code": _as_str(merged_reflection.get("reason_code")).strip(),
                "decision_source": "answer_commit",
                "retry_budget_snapshot": {
                    "generation_retries": int(loop_counts.get("generation_retries") or 0),
                    "retrieval_retries": int(loop_counts.get("retrieval_retries") or 0),
                },
                "round_id": _current_review_round(state),
                "completed_at": now_iso(),
            },
            updates=updates,
        ),
    }
    if final_answer:
        updates["final_answer"] = final_answer
    if next_step == "confidence_calibrate":
        if not final_answer:
            final_answer = "根据现有资料无法回答该问题（未生成答案）。"
            updates["final_answer"] = final_answer
        updates["messages"] = [AIMessage(content=final_answer)]
    return {
        **updates,
        **_merge_stage_summary(state, "answer_subgraph", summary, updates=updates),
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_commit",
                "next_step": next_step,
                "repair_attempts": repair_attempts,
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


def build_answer_subgraph(
    *,
    settings: Settings,
    chat_model: BaseChatModel,
):
    """Build compiled answer subgraph for parent KB chat graph."""

    graph = StateGraph(
        state_schema=KbChatInternalState,
        context_schema=KbChatAnswerSubgraphContext,
    )
    generation_retry_policy = RetryPolicy(
        max_attempts=max(2, int(getattr(settings, "kb_chat_max_generation_retries", 2)) + 1)
    )

    def add_traced_node(
        node_id: str,
        node_callable: Any,
        *,
        side_effect_type: str,
        retry_policy: RetryPolicy | None = None,
        retry_disabled_reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        metadata = extend_kb_chat_node_metadata(
            node_id,
            side_effect_type=side_effect_type,
            retry_enabled=retry_policy is not None,
        )
        if retry_policy is None:
            metadata["retry_disabled_reason"] = retry_disabled_reason or side_effect_type
        graph.add_node(
            node_id,
            wrap_kb_chat_node_with_io(node_id, node_callable),
            metadata=metadata,
            retry_policy=retry_policy,
            **kwargs,
        )

    add_traced_node(
        "draft_generate",
        lambda s, runtime: _draft_generate(
            s, runtime, settings=settings, chat_model=chat_model
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_review_dispatch",
        lambda s, runtime: _answer_review_dispatch(
            s,
            runtime,
            settings=settings,
        ),
        side_effect_type="deterministic_rule",
        retry_disabled_reason="parallel_fanout",
        destinations=(
            "answer_review_citation",
            "answer_review_factual",
            "answer_review_answerability",
            "answer_review_fuse",
        ),
    )
    add_traced_node(
        "answer_review_citation",
        lambda s, runtime: _answer_review_citation(s, runtime, settings=settings),
        side_effect_type="deterministic_rule",
    )
    add_traced_node(
        "answer_review_factual",
        lambda s, runtime: _answer_review_factual(
            s, runtime, settings=settings, chat_model=chat_model
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_review_answerability",
        lambda s, runtime: _answer_review_answerability(
            s, runtime, settings=settings, chat_model=chat_model
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_review_fuse",
        lambda s, runtime: _answer_review_fuse(
            s,
            runtime,
            settings=settings,
        ),
        side_effect_type="deterministic_rule",
        destinations=("cove_check", "answer_commit", "answer_repair"),
    )
    add_traced_node(
        "cove_check",
        _cove_check,
        side_effect_type="deterministic_rule",
        destinations=("chain_of_verification", "claim_citation_check"),
    )
    add_traced_node("chain_of_verification", _chain_of_verification, side_effect_type="deterministic_rule")
    add_traced_node(
        "claim_citation_check",
        _claim_citation_check,
        side_effect_type="deterministic_rule",
        destinations=("answer_commit", "answer_repair"),
    )
    add_traced_node(
        "answer_repair",
        lambda s, runtime: _answer_repair(s, runtime, settings=settings, chat_model=chat_model),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_commit",
        lambda s, runtime: _answer_commit(s, runtime, settings=settings),
        side_effect_type="deterministic_rule",
        defer=True,
    )

    graph.set_entry_point("draft_generate")
    graph.add_edge("draft_generate", "answer_review_dispatch")
    graph.add_edge("answer_review_citation", "answer_review_fuse")
    graph.add_edge("answer_review_factual", "answer_review_fuse")
    graph.add_edge("answer_review_answerability", "answer_review_fuse")
    graph.add_edge("chain_of_verification", "claim_citation_check")
    graph.add_edge("answer_repair", "answer_review_dispatch")
    graph.add_edge("answer_commit", END)
    return graph.compile(name="kb_chat_answer_subgraph")
