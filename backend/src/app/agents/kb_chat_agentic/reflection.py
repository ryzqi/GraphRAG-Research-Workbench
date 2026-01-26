"""KB Chat agentic ReflectionLayer nodes (relevance / hallucination / answer-check).

These nodes are designed to be:
- Minimal & production-safe (timeouts + fallbacks)
- Serializable-friendly (only write JSON-ish values to state)
- Budget-aware (bind routing to loop_counts budgets)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.core.settings import Settings, get_settings
from app.prompts import get_prompt_loader
from app.services.query_rewrite_service import QueryRewriteService, build_query_items

from .budget import effective_timeout_seconds, now_iso, remaining_budget_seconds
from .json_safety import ensure_json_safe

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)
_CITATION_RE = re.compile(r"\[(\d+)\]")
_EVIDENCE_LINE_RE = re.compile(r"^\[(\d+)\]\s+", re.MULTILINE)


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


def _deadline_exceeded(state: dict) -> bool:
    metrics = state.get("metrics")
    budget = metrics.get("budget") if isinstance(metrics, dict) else None
    deadline_ts = budget.get("deadline_ts") if isinstance(budget, dict) else None
    return isinstance(deadline_ts, (int, float)) and time.time() > float(deadline_ts)


def _total_rounds_exceeded(loop_counts: dict[str, int], settings: Settings) -> bool:
    return loop_counts.get("total_rounds", 0) >= int(settings.kb_chat_max_total_rounds)


def _extract_evidence_count(final_context: str) -> int:
    if not final_context:
        return 0
    matches = [int(m.group(1)) for m in _EVIDENCE_LINE_RE.finditer(final_context)]
    return max(matches) if matches else 0


def _extract_valid_citations(answer: str, *, evidence_count: int) -> set[int]:
    if not answer or evidence_count <= 0:
        return set()
    found: set[int] = set()
    for raw in _CITATION_RE.findall(answer):
        try:
            idx = int(raw)
        except Exception:
            continue
        if 1 <= idx <= evidence_count:
            found.add(idx)
    return found


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    # Remove leading/trailing ``` fences to improve JSON parse stability.
    return _CODE_FENCE_RE.sub("", text).strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fences(text)
    if not cleaned:
        return None
    m = _JSON_OBJ_RE.search(cleaned)
    payload = m.group(0) if m else cleaned
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _render_prompt_or_default(prompt_key: str, default: str) -> str:
    prompts = get_prompt_loader()
    try:
        return prompts.render(prompt_key)
    except KeyError:
        return default


async def _judge_json(
    *,
    chat_model: ChatOpenAI,
    system: str,
    user: str,
    timeout_seconds: float,
    max_tokens: int,
) -> tuple[dict[str, Any] | None, str | None]:
    model = chat_model.bind(temperature=0, max_tokens=max_tokens)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    try:
        msg = await asyncio.wait_for(
            model.ainvoke(messages), timeout=float(timeout_seconds)
        )
    except asyncio.TimeoutError:
        return None, "timeout"
    except asyncio.CancelledError:
        raise
    except Exception:
        return None, "exception"
    parsed = _parse_json_object(_as_str(getattr(msg, "content", "")))
    if parsed is None:
        return None, "invalid_json"
    return parsed, None


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


def _retrieval_attempted(state: dict) -> bool:
    metrics = state.get("metrics")
    retrieval_layer = (
        metrics.get("retrieval_layer") if isinstance(metrics, dict) else None
    )
    if isinstance(retrieval_layer, dict):
        if retrieval_layer.get("attempted") is True:
            return True
    stage_summaries = state.get("stage_summaries")
    return isinstance(stage_summaries, dict) and "retrieval_layer" in stage_summaries


async def kb_retrieve_context(
    state: dict,
    *,
    settings: Settings,
    kb_tool: BaseTool,
) -> dict[str, Any]:
    """Run kb_retrieve once and store the resulting Top-N context into state.final_context."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    remaining = remaining_budget_seconds(state, settings)
    if remaining <= 0:
        metrics = state.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        metrics = {
            **metrics,
            "retrieval_layer": {"evidence_count": 0, "attempted": False},
        }
        metrics = ensure_json_safe(metrics, settings=settings, label="metrics")
        return {
            **_set_final_answer_for_exit(state, "", reason="budget_exhausted"),
            "metrics": metrics,
            **_merge_stage_summary(
                state,
                "retrieval_layer",
                {
                    "skipped": True,
                    "reason": "budget_exhausted",
                    "evidence_count": 0,
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "completed_at": now_iso(),
                },
            ),
        }
    if _total_rounds_exceeded(loop_counts, settings):
        return _set_final_answer_for_exit(state, "", reason="max_total_rounds")
    query = _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("merged_context")
        or state.get("user_input")
    ).strip()
    memory_keys = state.get("memory_keys")
    kb_ids = memory_keys.get("kb_ids") if isinstance(memory_keys, dict) else None
    if not isinstance(kb_ids, list):
        kb_ids = None

    retrieval_reason: str | None = None
    try:
        payload: dict[str, Any] = {
            "query": query,
            "kb_ids": kb_ids,
            # Use RetrievalService default when omitted.
            "top_k": None,
            "timeout_seconds": remaining,
        }
        query_items = state.get("query_items")
        if isinstance(query_items, list) and query_items:
            # Pass fanout query bundle to kb_retrieve so RetrievalService.retrieve_layer() can do cross-query fusion.
            payload["query_items"] = query_items
        context = await asyncio.wait_for(
            kb_tool.ainvoke(payload), timeout=effective_timeout_seconds(None, remaining)
        )
    except asyncio.TimeoutError:
        retrieval_reason = "timeout"
        context = "（未找到相关内容）"
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
    question = _as_str(state.get("merged_context") or state.get("user_input")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    evidence_count = _extract_evidence_count(final_context)

    passed = False
    reason = "no_evidence"
    fallback_used = False
    fallback_reason: str | None = None
    if evidence_count > 0 and "未找到相关内容" not in final_context:
        system_prompt = _render_prompt_or_default(
            "kb_chat/doc_grader",
            (
                "你是严格的检索相关性评估器。判断“检索片段”是否与“问题”相关且足以支撑回答。"
                '仅输出 JSON：{"passed": true/false, "reason": "..."}。'
            ),
        )
        judge: dict[str, Any] | None = None
        remaining = remaining_budget_seconds(state, settings)
        if remaining <= 0:
            fallback_used = True
            fallback_reason = "budget_exhausted"
        else:
            timeout_value = effective_timeout_seconds(
                settings.llm_timeout_seconds, remaining
            )
            if timeout_value <= 0:
                fallback_used = True
                fallback_reason = "budget_exhausted"
            else:
                judge, fallback_reason = await _judge_json(
                    chat_model=chat_model,
                    system=system_prompt,
                    user=f"问题：{question}\n\n检索片段：\n{final_context[:4000]}",
                    timeout_seconds=timeout_value,
                    max_tokens=128,
                )
                if judge is None:
                    fallback_used = True
        if isinstance(judge, dict):
            passed = bool(judge.get("passed"))
            reason = _as_str(judge.get("reason") or "").strip() or (
                "passed" if passed else "not_relevant"
            )
        else:
            policy = settings.kb_chat_grader_fail_policy
            passed = policy == "open"
            reason = fallback_reason or (
                "fallback_open" if passed else "fallback_closed"
            )
            if fallback_reason is None:
                fallback_reason = "invalid_json"

    action = "none" if passed else "transform_query"
    exit_updates: dict[str, Any] = {}
    if fallback_reason == "budget_exhausted":
        action = "force_exit"
        reason = "budget_exhausted"
        exit_updates = _set_final_answer_for_exit(state, "", reason="budget_exhausted")

    updates: dict[str, Any] = {
        **exit_updates,
        **_merge_reflection(
            state,
            {
                "relevance_passed": passed,
                "action": action,
                "reason": reason,
            },
        ),
        **_merge_stage_summary(
            state,
            "doc_grader",
            {
                "passed": passed,
                "reason": reason,
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
    strict: bool,
) -> dict[str, Any]:
    """Generate a draft answer using ONLY Top-N final_context; do not append to messages."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    remaining = remaining_budget_seconds(state, settings)
    if remaining <= 0:
        return {
            **_set_final_answer_for_exit(
                state, _as_str(state.get("draft_answer")), reason="budget_exhausted"
            ),
            **_merge_stage_summary(
                state,
                "generator",
                {
                    "strict": strict,
                    "skipped": True,
                    "reason": "budget_exhausted",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "completed_at": now_iso(),
                },
            ),
        }

    # Budget accounting: count each generation as one "round".
    loop_counts = {**loop_counts, "total_rounds": loop_counts["total_rounds"] + 1}
    if strict:
        loop_counts = {
            **loop_counts,
            "generation_retries": loop_counts["generation_retries"] + 1,
        }

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

    question = _as_str(state.get("merged_context") or state.get("user_input")).strip()
    final_context = _as_str(state.get("final_context")).strip()
    prompts = get_prompt_loader()
    system_prompt = prompts.render("kb_chat/system")
    if strict:
        system_prompt = (
            f"{system_prompt}\n\n"
            "你的上一版回答存在“幻觉/引用不匹配/答非所问”等问题。请严格基于参考内容重新生成，"
            "不要添加任何参考内容中没有的信息；每个关键事实都需要在句末给出引用编号。"
        )

    user = f"参考内容：\n{final_context}\n\n问题：{question}"

    timeout_value = effective_timeout_seconds(settings.llm_timeout_seconds, remaining)
    if timeout_value <= 0:
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state, _as_str(state.get("draft_answer")), reason="budget_exhausted"
            ),
        }

    model = chat_model.bind(max_tokens=1024)
    try:
        msg = await asyncio.wait_for(
            model.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user)]
            ),
            timeout=timeout_value,
        )
        draft = _as_str(getattr(msg, "content", "")).strip()
    except asyncio.TimeoutError:
        draft = ""
    except asyncio.CancelledError:
        raise
    except Exception:
        draft = ""

    if not draft:
        draft = "根据现有资料无法回答该问题（生成失败或超时）。"

    return {
        "loop_counts": loop_counts,
        "draft_answer": draft,
        # Keep final_answer aligned so ForceExit can always return something sane.
        "final_answer": draft,
        **_merge_stage_summary(
            state,
            "generator",
            {
                "strict": strict,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def hallucination_check(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Check hallucination / citation mismatch for the current draft answer."""
    start = time.perf_counter()
    final_context = _as_str(state.get("final_context")).strip()
    draft = _as_str(state.get("draft_answer")).strip()

    evidence_count = _extract_evidence_count(final_context)
    valid_citations = _extract_valid_citations(draft, evidence_count=evidence_count)
    fallback_used = False
    fallback_reason: str | None = None
    if evidence_count <= 0:
        passed = False
        reason = "no_evidence"
    elif not valid_citations:
        passed = False
        reason = "missing_or_invalid_citations"
    else:
        system_prompt = _render_prompt_or_default(
            "kb_chat/hallucination_check",
            (
                "你是严格的事实一致性评估器。判断“回答”是否完全由“参考内容”支持，"
                '且引用编号有效。仅输出 JSON：{"passed": true/false, "reason": "..."}。'
            ),
        )
        judge: dict[str, Any] | None = None
        remaining = remaining_budget_seconds(state, settings)
        if remaining <= 0:
            fallback_used = True
            fallback_reason = "budget_exhausted"
        else:
            timeout_value = effective_timeout_seconds(
                settings.llm_timeout_seconds, remaining
            )
            if timeout_value <= 0:
                fallback_used = True
                fallback_reason = "budget_exhausted"
            else:
                judge, fallback_reason = await _judge_json(
                    chat_model=chat_model,
                    system=system_prompt,
                    user=(
                        f"参考内容：\n{final_context[:4000]}\n\n回答：\n{draft[:1500]}"
                    ),
                    timeout_seconds=timeout_value,
                    max_tokens=128,
                )
                if judge is None:
                    fallback_used = True
        if isinstance(judge, dict):
            passed = bool(judge.get("passed"))
            reason = _as_str(judge.get("reason") or "").strip() or (
                "passed" if passed else "not_supported"
            )
        else:
            policy = settings.kb_chat_grader_fail_policy
            passed = policy == "open"
            reason = fallback_reason or (
                "fallback_open" if passed else "fallback_closed"
            )
            if fallback_reason is None:
                fallback_reason = "invalid_json"

    action = "none"
    exit_updates: dict[str, Any] = {}
    if fallback_reason == "budget_exhausted":
        action = "force_exit"
        reason = "budget_exhausted"
        exit_updates = _set_final_answer_for_exit(
            state, _as_str(state.get("draft_answer")), reason="budget_exhausted"
        )

    return {
        **exit_updates,
        **_merge_reflection(
            state,
            {
                "hallucination_passed": passed,
                "action": action,
                "reason": reason,
            },
        ),
        **_merge_stage_summary(
            state,
            "hallucination_check",
            {
                "passed": passed,
                "reason": reason,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def answer_check(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Check whether the draft answer addresses the question (off-topic guard)."""
    start = time.perf_counter()
    question = _as_str(state.get("merged_context") or state.get("user_input")).strip()
    draft = _as_str(state.get("draft_answer")).strip()

    passed = False
    reason = "empty"
    fallback_used = False
    fallback_reason: str | None = None
    if draft:
        system_prompt = _render_prompt_or_default(
            "kb_chat/answer_check",
            (
                "你是严格的答复有效性评估器。判断“回答”是否直接回答“问题”，"
                '是否答非所问。仅输出 JSON：{"passed": true/false, "reason": "..."}。'
            ),
        )
        judge: dict[str, Any] | None = None
        remaining = remaining_budget_seconds(state, settings)
        if remaining <= 0:
            fallback_used = True
            fallback_reason = "budget_exhausted"
        else:
            timeout_value = effective_timeout_seconds(
                settings.llm_timeout_seconds, remaining
            )
            if timeout_value <= 0:
                fallback_used = True
                fallback_reason = "budget_exhausted"
            else:
                judge, fallback_reason = await _judge_json(
                    chat_model=chat_model,
                    system=system_prompt,
                    user=f"问题：{question}\n\n回答：\n{draft[:2000]}",
                    timeout_seconds=timeout_value,
                    max_tokens=128,
                )
                if judge is None:
                    fallback_used = True
        if isinstance(judge, dict):
            passed = bool(judge.get("passed"))
            reason = _as_str(judge.get("reason") or "").strip() or (
                "passed" if passed else "off_topic"
            )
        else:
            policy = settings.kb_chat_grader_fail_policy
            passed = policy == "open"
            reason = fallback_reason or (
                "fallback_open" if passed else "fallback_closed"
            )
            if fallback_reason is None:
                fallback_reason = "invalid_json"

    action = "none" if passed else "transform_query"
    exit_updates: dict[str, Any] = {}
    if fallback_reason == "budget_exhausted":
        action = "force_exit"
        reason = "budget_exhausted"
        exit_updates = _set_final_answer_for_exit(
            state, _as_str(state.get("draft_answer")), reason="budget_exhausted"
        )

    return {
        **exit_updates,
        **_merge_reflection(
            state,
            {
                "answer_passed": passed,
                "action": action,
                "reason": reason,
            },
        ),
        **_merge_stage_summary(
            state,
            "answer_check",
            {
                "passed": passed,
                "reason": reason,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
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
    if remaining_budget_seconds(state, settings) <= 0:
        return _set_final_answer_for_exit(
            state, _as_str(state.get("draft_answer")), reason="budget_exhausted"
        )

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

    current = _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("merged_context")
        or state.get("user_input")
    ).strip()
    reflection = state.get("reflection")
    reason = reflection.get("reason") if isinstance(reflection, dict) else None

    new_query = current
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.transform_query(current, reason=_as_str(reason) or "retry")
        if result.query.strip():
            new_query = result.query.strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        new_query = current

    # Keep query bundle consistent: after transform, reset fanout artifacts.
    query_items = build_query_items(main_query=new_query)

    return {
        "loop_counts": loop_counts,
        "normalized_query": new_query,
        "coref_query": new_query,
        "sub_queries": [],
        "multi_queries": [],
        "hyde_doc": "",
        "query_items": query_items,
        **_merge_reflection(
            state, {"action": "transform_query", "reason": _as_str(reason) or "retry"}
        ),
        **_merge_stage_summary(
            state,
            "transform_query",
            {
                "rewritten": new_query != current,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


def route_after_doc_grader(state: dict, settings: Settings) -> str:
    """Route after DocGrader: generate vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    if _deadline_exceeded(state):
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


def route_after_hallucination(state: dict, settings: Settings) -> str:
    """Route after HallucinationCheck: answer_check vs strict_regen vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    if _deadline_exceeded(state):
        return "force_exit"
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return "force_exit"

    reflection = state.get("reflection")
    passed = (
        reflection.get("hallucination_passed") if isinstance(reflection, dict) else None
    )
    if passed is True:
        return "answer_check"

    # First try strict regeneration within generation budget.
    if loop_counts["generation_retries"] < int(settings.kb_chat_max_generation_retries):
        return "generate_strict"

    # If regeneration budget is exhausted, fall back to query transform (if available).
    if loop_counts["retrieval_retries"] < int(settings.kb_chat_max_retrieval_retries):
        return "transform_query"
    return "force_exit"


def route_after_answer_check(state: dict, settings: Settings) -> str:
    """Route after AnswerCheck: finalize vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    if _deadline_exceeded(state):
        return "force_exit"
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return "force_exit"

    force_retrieve = bool(state.get("force_kb_retrieve"))
    if force_retrieve and not _retrieval_attempted(state):
        if loop_counts["retrieval_retries"] < int(
            settings.kb_chat_max_retrieval_retries
        ):
            return "transform_query"
        return "force_exit"

    reflection = state.get("reflection")
    passed = reflection.get("answer_passed") if isinstance(reflection, dict) else None
    if passed is True:
        return "finalize"

    if loop_counts["retrieval_retries"] < int(settings.kb_chat_max_retrieval_retries):
        return "transform_query"
    return "force_exit"


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
