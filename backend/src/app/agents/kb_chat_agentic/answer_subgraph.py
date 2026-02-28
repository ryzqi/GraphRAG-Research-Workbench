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
from langchain.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send
from pydantic import ValidationError

from app.agents.kb_chat_agentic.reflection import (
    generate_draft,
    route_after_answer_review,
)
from app.agents.kb_chat_agentic.schemas import AnswerReviewSubDecision
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings
from app.prompts import get_prompt_loader

from .budget import now_iso

_REPAIRABLE_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
}
_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
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
    return [f"[{match.group(1).strip()}]" for match in re.finditer(r"\[([^\[\]\n]{1,128})\]", answer)]


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
    chat_model: ChatOpenAI,
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


def _resolve_subcheck(state: dict[str, Any], check: str) -> dict[str, Any] | None:
    runs = state.get("answer_review_runs")
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict):
            continue
        if _as_str(run.get("check")) == check:
            return run
    return None


async def _answer_review_dispatch(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> Command[str]:
    _ = runtime, settings
    send_tasks: list[Send] = [
        Send("answer_review_citation", {"answer_review_task": {"check": "citation"}}),
        Send("answer_review_factual", {"answer_review_task": {"check": "factual"}}),
        Send(
            "answer_review_answerability",
            {"answer_review_task": {"check": "answerability"}},
        ),
    ]
    return Command(
        update={
            "answer_review_runs": [],
            **_merge_subgraph_state(
                state,
                {"phase": "answer_review_dispatch", "last_updated_at": now_iso()},
            ),
            **_merge_stage_summary(
                state,
                "answer_review_dispatch",
                {
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
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> dict[str, Any]:
    _ = runtime, settings
    start = time.perf_counter()
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
    state: dict[str, Any],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
    check: Literal["factual", "answerability"],
) -> dict[str, Any]:
    start = time.perf_counter()
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
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    _ = runtime
    return await _answer_review_llm_check(
        state, settings=settings, chat_model=chat_model, check="factual"
    )


async def _answer_review_answerability(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    _ = runtime
    return await _answer_review_llm_check(
        state, settings=settings, chat_model=chat_model, check="answerability"
    )


async def _answer_review_fuse(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> Command[str]:
    _ = runtime
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    loop_counts_updates = {
        **loop_counts,
        "total_rounds": loop_counts.get("total_rounds", 0) + 1,
    }
    by_check = {
        check: (_resolve_subcheck(state, check) or {"check": check, "passed": False, "reason": "fallback_closed"})
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
    best_answer_updates: dict[str, Any] = {}
    best_answer_meta: dict[str, Any] | None = None
    if passed and draft:
        best_answer_meta = {
            "from_node": "answer_review_fuse",
            "reason": reason,
            "retrieval_round": max(loop_counts.get("retrieval_retries", 0), 0),
            "total_rounds": loop_counts_updates.get("total_rounds", 0),
            "completed_at": now_iso(),
        }
        best_answer_updates = {"best_answer": draft, "best_answer_meta": best_answer_meta}
    stage_summary = {
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
        **best_answer_updates,
        "answer_review_runs": [],
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
    if not passed and _as_str(reason) not in _REPAIRABLE_FAILURE_REASONS:
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


def _is_high_risk_query(state: dict[str, Any]) -> bool:
    query = _resolve_query_text(state)
    lowered = query.lower()
    return any(hint in query for hint in _HIGH_RISK_HINTS) or "risk" in lowered


def _cove_check(state: dict[str, Any]) -> Command[str]:
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


def _chain_of_verification(state: dict[str, Any]) -> dict[str, Any]:
    draft = _as_str(state.get("draft_answer")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    citations = _extract_citations(draft)
    passed = bool(draft and final_context and citations)
    reason = "passed" if passed else "insufficient_verification_signal"
    stage = _merge_stage_summary(
        state,
        "chain_of_verification",
        {
            "passed": passed,
            "reason": reason,
            "citation_count": len(citations),
            "completed_at": now_iso(),
        },
    )
    return {
        "cove_state": {
            "enabled": True,
            "triggered": True,
            "passed": passed,
            "reason": reason,
            "citation_count": len(citations),
        },
        **stage,
    }


def _claim_citation_check(state: dict[str, Any]) -> Command[str]:
    draft = _as_str(state.get("draft_answer")).strip()
    labels = _extract_evidence_labels(_as_str(state.get("final_context")).strip())
    _, valid_citations, invalid_citations = _partition_citations(
        draft, allowed_labels=labels
    )
    cove_state = state.get("cove_state")
    cove_passed = (
        cove_state.get("passed")
        if isinstance(cove_state, dict) and cove_state.get("passed") is not None
        else True
    )
    citation_passed = bool(draft) and bool(valid_citations) and not invalid_citations
    passed = bool(cove_passed) and citation_passed
    reason = "passed"
    if not cove_passed:
        reason = "cove_failed"
    elif invalid_citations:
        reason = "invalid_citations"
    elif not valid_citations:
        reason = "missing_citations"

    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    reflection_patch: dict[str, Any] = {}
    if not passed:
        reflection_patch = {
            "review_passed": False,
            "action": "transform_query",
            "reason": reason,
        }

    stage = _merge_stage_summary(
        state,
        "claim_citation_check",
        {
            "passed": passed,
            "reason": reason,
            "valid_citation_count": len(valid_citations),
            "invalid_citations": sorted(invalid_citations),
            "completed_at": now_iso(),
        },
        updates={"reflection": {**reflection_obj, **reflection_patch}},
    )
    return Command(
        update={
            "cove_state": {
                **(cove_state if isinstance(cove_state, dict) else {}),
                "claim_check_passed": passed,
                "claim_check_reason": reason,
            },
            "reflection": {**reflection_obj, **reflection_patch},
            **stage,
        },
        goto="answer_commit" if passed else "answer_repair",
    )


async def _draft_generate(
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
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
    state: dict[str, Any],
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    _ = runtime
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    loop_counts = {
        **loop_counts,
        "total_rounds": loop_counts["total_rounds"] + 1,
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
            candidate = _as_str(getattr(msg, "content", "")).strip()
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
    state: dict[str, Any],
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

    next_step = route_after_answer_review(state, settings)
    reason = _as_str(reflection_obj.get("reason")).strip()
    degrade_reason: str | None = None
    reflection_patch: dict[str, Any] = {}

    if loop_counts["generation_retries"] >= int(settings.kb_chat_max_generation_retries):
        next_step = "force_exit"
        degrade_reason = "max_generation_retries"
        reflection_patch = {
            "action": "force_exit",
            "reason": "max_generation_retries",
            "review_passed": False,
        }
    elif next_step == "force_exit":
        degrade_reason = reason or "force_exit"
        reflection_patch = {"action": "force_exit"}
    elif next_step == "transform_query":
        degrade_reason = reason or "review_failed"
        reflection_patch = {"action": "transform_query"}
    else:
        reflection_patch = {"action": "none"}

    merged_reflection = {**reflection_obj, **reflection_patch}
    final_answer = _as_str(state.get("final_answer") or state.get("draft_answer")).strip()
    if not final_answer and next_step == "force_exit":
        final_answer = "基于当前信息仍无法稳定回答该问题（已停止重试）。"

    answer_quality = {
        "passed": merged_reflection.get("review_passed") is True,
        "reason": _as_str(merged_reflection.get("reason")).strip(),
        "next_step": next_step,
        "repair_attempts": repair_attempts,
        "generation_retries": loop_counts.get("generation_retries", 0),
        "retrieval_retries": loop_counts.get("retrieval_retries", 0),
    }
    best_answer = _as_str(state.get("best_answer") or state.get("draft_answer")).strip()
    summary = {
        **answer_quality,
        "best_answer": best_answer or None,
        "degrade_reason": degrade_reason,
        "completed_at": now_iso(),
    }

    updates: dict[str, Any] = {
        "reflection": merged_reflection,
        "answer_quality": answer_quality,
        "degrade_reason": degrade_reason,
    }
    if final_answer:
        updates["final_answer"] = final_answer
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
    chat_model: ChatOpenAI,
):
    """Build compiled answer subgraph for parent KB chat graph."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatAnswerSubgraphContext,
    )
    graph.add_node(
        "draft_generate",
        lambda s, runtime: _draft_generate(
            s, runtime, settings=settings, chat_model=chat_model
        ),
    )
    graph.add_node(
        "answer_review_dispatch",
        lambda s, runtime: _answer_review_dispatch(
            s,
            runtime,
            settings=settings,
        ),
        destinations=(
            "answer_review_citation",
            "answer_review_factual",
            "answer_review_answerability",
            "answer_review_fuse",
        ),
    )
    graph.add_node(
        "answer_review_citation",
        lambda s, runtime: _answer_review_citation(s, runtime, settings=settings),
    )
    graph.add_node(
        "answer_review_factual",
        lambda s, runtime: _answer_review_factual(
            s, runtime, settings=settings, chat_model=chat_model
        ),
    )
    graph.add_node(
        "answer_review_answerability",
        lambda s, runtime: _answer_review_answerability(
            s, runtime, settings=settings, chat_model=chat_model
        ),
    )
    graph.add_node(
        "answer_review_fuse",
        lambda s, runtime: _answer_review_fuse(
            s,
            runtime,
            settings=settings,
        ),
        destinations=("cove_check", "answer_commit", "answer_repair"),
    )
    graph.add_node("cove_check", _cove_check, destinations=("chain_of_verification", "claim_citation_check"))
    graph.add_node("chain_of_verification", _chain_of_verification)
    graph.add_node(
        "claim_citation_check",
        _claim_citation_check,
        destinations=("answer_commit", "answer_repair"),
    )
    graph.add_node(
        "answer_repair",
        lambda s, runtime: _answer_repair(s, runtime, settings=settings, chat_model=chat_model),
    )
    graph.add_node(
        "answer_commit",
        lambda s, runtime: _answer_commit(s, runtime, settings=settings),
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
