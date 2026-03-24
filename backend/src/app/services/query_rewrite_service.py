"""Query enhancement service (rewrite / clarify / fanout helpers).

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
from dataclasses import dataclass
from typing import Iterable

from langchain.agents import create_agent
from pydantic import BaseModel, ValidationError

from app.agents.kb_chat_agentic.schemas import (
    AmbiguityDecision,
    ClarificationSlotDecision,
    COMPLEXITY_CLASSIFY_DECISION_VERSION,
    ComplexityDecision,
    DecompositionDecision,
    HyDEBatchDecision,
    MergeContextResolutionDecision,
    MultiQueryDecision,
    NormalizeDecision,
    ReferenceResolutionDecision,
    RetrievalPlanDecision,
    TransformQueryDecision,
)
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.prompts import get_prompt_loader
from app.schemas.query_enhancement import QueryItem
from app.utils.text_sanitization import sanitize_visible_text

logger = logging.getLogger(__name__)

DECOMPOSITION_MAX_SUB_QUERIES = 5
MULTI_QUERY_FIXED_VARIANTS = 3
HYDE_NUM_HYPOTHESES = 5
HYDE_AGGREGATION = "mean_embedding"
HYDE_REGENERATE_ON_RETRY = True
STRUCTURED_CALL_RETRYABLE_REASONS = frozenset(
    {"error", "empty_structured_response", "invalid_schema"}
)
STRUCTURED_CALL_MAX_ATTEMPTS = 2


@dataclass(slots=True)
class RewriteResult:
    query: str
    rewritten: bool
    reason: str | None = None
    latency_ms: int | None = None
    meta: dict[str, object] | None = None


@dataclass(slots=True)
class QueryListResult:
    queries: list[str]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None
    plan: dict[str, object] | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(slots=True)
class AmbiguityResult:
    ambiguous: bool
    reverse_question: str | None = None
    reason: str | None = None
    failure_reason: str | None = None
    latency_ms: int | None = None
    reason_code: str | None = None
    confidence: float | None = None
    model_reason: str | None = None
    fallback_used: bool = False
    clarification_payload: dict[str, object] | None = None


@dataclass(slots=True)
class ComplexityRouteResult:
    strategy: str
    success: bool
    reasoning: str | None = None
    failure_reason: str | None = None
    confidence: float = 0.0
    risk_flags: list[str] | None = None
    decision_version: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class StructuredCallResult:
    payload: BaseModel | None = None
    success: bool = False
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class MergeContextResolutionResult:
    summary_text: str
    keep_memory: bool
    notes: list[str]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class RetrievalPlanResult:
    budget: dict[str, int]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None
    meta: dict[str, object] | None = None


def _extract_structured_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            for key in ("text", "content"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    chunks.append(raw.strip())
                    break
        return "\n".join(chunks).strip()
    return ""


def _debug_preview(value: object, *, limit: int = 1600) -> str:
    if isinstance(value, BaseModel):
        serializable: object = value.model_dump(mode="json")
    else:
        serializable = value
    try:
        rendered = json.dumps(serializable, ensure_ascii=False, default=str)
    except TypeError:
        rendered = repr(serializable)
    rendered = rendered.strip()
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[:limit]}…"


def _looks_like_json_object_key(raw: str, start: int) -> bool:
    if start >= len(raw) or raw[start] != '"':
        return False

    i = start + 1
    escaped = False
    while i < len(raw):
        ch = raw[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            i += 1
            while i < len(raw) and raw[i].isspace():
                i += 1
            return i < len(raw) and raw[i] == ":"
        i += 1
    return False


def _repair_missing_array_object_start(raw: str) -> str | None:
    """修复数组对象项丢失起始 `{` 的近似 JSON 漂移。"""

    result: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    just_closed_object_in_array = False
    pending_array_item_after_comma = False
    changed = False

    for index, ch in enumerate(raw):
        if pending_array_item_after_comma:
            if ch.isspace():
                result.append(ch)
                continue
            if ch == '"' and _looks_like_json_object_key(raw, index):
                result.append("{")
                stack.append("{")
                changed = True
            pending_array_item_after_comma = False

        result.append(ch)

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            just_closed_object_in_array = False
            continue
        if ch == "{":
            stack.append("{")
            just_closed_object_in_array = False
            continue
        if ch == "[":
            stack.append("[")
            just_closed_object_in_array = False
            continue
        if ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
            just_closed_object_in_array = bool(stack and stack[-1] == "[")
            continue
        if ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
            just_closed_object_in_array = False
            continue
        if ch == ",":
            if just_closed_object_in_array:
                pending_array_item_after_comma = True
            just_closed_object_in_array = False
            continue
        if not ch.isspace():
            just_closed_object_in_array = False

    if not changed:
        return None
    return "".join(result)


def _repair_common_malformed_json(raw: str) -> str | None:
    """修复部分模型在 raw structured 文本里常见的近似 JSON 漂移。"""

    repaired = re.sub(r'(?<=\[)\s*"(?=\{)', "", raw)
    repaired = re.sub(r'(?<=,)\s*"(?=\{)', "", repaired)
    repaired = re.sub(r'}\s*,\s*"\s*}\s*,\s*(?=\{)', "},", repaired)
    repaired_array_object_start = _repair_missing_array_object_start(repaired)
    if repaired_array_object_start is not None:
        repaired = repaired_array_object_start
    if repaired == raw:
        return None
    return repaired


def _coerce_schema_from_json_like(
    *,
    value: object,
    schema: type[BaseModel],
) -> tuple[BaseModel | None, str | None]:
    if isinstance(value, schema):
        return value, None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, "empty_structured_response"

        candidates = [raw]
        repaired = _repair_common_malformed_json(raw)
        if repaired and repaired not in candidates:
            candidates.append(repaired)

        for candidate in candidates:
            try:
                return schema.model_validate_json(candidate), None
            except ValidationError:
                try:
                    value = json.loads(candidate)
                except (TypeError, ValueError):
                    continue
                try:
                    return schema.model_validate(value), None
                except ValidationError:
                    continue
        return None, "invalid_schema"
    try:
        return schema.model_validate(value), None
    except ValidationError:
        return None, "invalid_schema"


def _extract_tool_call_payload(raw: object) -> tuple[object | None, str | None]:
    tool_calls = getattr(raw, "tool_calls", None)
    if isinstance(tool_calls, list) and tool_calls:
        if len(tool_calls) > 1:
            return None, "multiple_structured_outputs"
        if isinstance(tool_calls[0], dict) and "args" in tool_calls[0]:
            return tool_calls[0].get("args"), None

    content = getattr(raw, "content", None)
    if isinstance(content, list) and content:
        content_payloads: list[object] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip().lower()
            if block_type not in {"tool_use", "tool_call"}:
                continue
            for key in ("input", "args"):
                if key in block:
                    content_payloads.append(block.get(key))
                    break
        if len(content_payloads) > 1:
            return None, "multiple_structured_outputs"
        if content_payloads:
            return content_payloads[0], None

    additional_kwargs = getattr(raw, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        openai_tool_calls = additional_kwargs.get("tool_calls")
        if isinstance(openai_tool_calls, list) and openai_tool_calls:
            if len(openai_tool_calls) > 1:
                return None, "multiple_structured_outputs"
            call = openai_tool_calls[0]
            if isinstance(call, dict):
                function = call.get("function")
                if isinstance(function, dict) and "arguments" in function:
                    return function.get("arguments"), None
    return None, None


def coerce_structured_result_payload(
    *,
    result: object,
    schema: type[BaseModel],
) -> tuple[BaseModel | None, str | None]:
    if result is None:
        return None, "empty_structured_response"

    if isinstance(result, schema):
        return result, None

    if isinstance(result, dict):
        parsed = result.get("parsed")
        if isinstance(parsed, schema):
            return parsed, None
        if parsed is not None:
            try:
                return schema.model_validate(parsed), None
            except ValidationError:
                pass

        raw = result.get("raw")
        tool_payload, tool_payload_error = _extract_tool_call_payload(raw)
        tool_payload_invalid = False
        if tool_payload_error is not None:
            return None, tool_payload_error
        if tool_payload is not None:
            payload, reason = _coerce_schema_from_json_like(
                value=tool_payload,
                schema=schema,
            )
            if payload is not None or reason != "invalid_schema":
                return payload, reason
            tool_payload_invalid = True
        raw_content = _extract_structured_text(getattr(raw, "content", raw))
        if raw_content:
            return _coerce_schema_from_json_like(value=raw_content, schema=schema)
        if tool_payload_invalid:
            return None, "invalid_schema"

        try:
            return schema.model_validate(result), None
        except ValidationError:
            parsing_error = result.get("parsing_error")
            if parsing_error is not None:
                return None, "invalid_schema"
            return None, "empty_structured_response"

    raw_content = _extract_structured_text(getattr(result, "content", result))
    if raw_content:
        return _coerce_schema_from_json_like(value=raw_content, schema=schema)

    return _coerce_schema_from_json_like(value=result, schema=schema)


def _structured_result_debug_snapshot(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        return {
            "result_type": type(result).__name__,
            "result_preview": _debug_preview(result),
        }

    raw = result.get("raw")
    tool_payload, tool_payload_error = _extract_tool_call_payload(raw)
    return {
        "result_type": "dict",
        "parsed_type": type(result.get("parsed")).__name__ if result.get("parsed") is not None else None,
        "parsed_preview": _debug_preview(result.get("parsed")),
        "parsing_error_type": (
            type(result.get("parsing_error")).__name__
            if result.get("parsing_error") is not None
            else None
        ),
        "parsing_error_preview": _debug_preview(result.get("parsing_error")),
        "raw_type": type(raw).__name__ if raw is not None else None,
        "raw_content_preview": _debug_preview(getattr(raw, "content", None)),
        "raw_tool_calls_preview": _debug_preview(getattr(raw, "tool_calls", None)),
        "raw_additional_kwargs_preview": _debug_preview(getattr(raw, "additional_kwargs", None)),
        "tool_payload_error": tool_payload_error,
        "tool_payload_preview": _debug_preview(tool_payload),
    }


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\\s+", " ", sanitize_visible_text(text)).strip()


def _normalize_single_line(text: str) -> str:
    for line in text.splitlines():
        normalized = _normalize_whitespace(line)
        if normalized:
            return normalized
    return _normalize_whitespace(text)


def _sanitize_query_text(text: str) -> str:
    return _normalize_single_line(text).strip("`\"' ")


_COREF_MARKERS_ZH = [
    "这个",
    "那个",
    "这些",
    "那些",
    "它",
    "他",
    "她",
    "他们",
    "她们",
    "它们",
    "上面",
    "前面",
    "刚才",
]
_COREF_MARKERS_EN = ["this", "that", "these", "those", "it", "they", "them"]
_COREF_MARKERS = sorted([*_COREF_MARKERS_ZH, *_COREF_MARKERS_EN], key=len, reverse=True)
_COREF_CONFIDENCE_THRESHOLD = 0.72
_DEFAULT_CLARIFICATION_QUESTION = (
    "为了更准确地回答，请补充你指的是哪个对象、范围或时间？"
)
_DEFAULT_AMBIGUITY_TRUE_REASON = "问题缺少关键信息，需先澄清后再检索。"
_DEFAULT_AMBIGUITY_FALSE_REASON = "未命中需澄清信号，可直接继续检索。"
_DEFAULT_COMPLEXITY_DIRECT_REASON = "未命中复杂问题信号，先按简单问题直接检索。"
_DEFAULT_COMPLEXITY_MULTI_QUERY_REASON = "目标单一但召回风险较高，按多路查询扩展检索。"
_DEFAULT_COMPLEXITY_DECOMPOSITION_REASON = "命中比较或多目标信号，按问题拆解处理。"
_GUARDRAIL_COMPLEXITY_DIRECT_REASON = "命中稳定实体的清单型问题信号，应优先直接检索。"
_GUARDRAIL_COMPLEXITY_DECOMPOSITION_REASON = (
    "命中“分别/各自”等并列子问题信号，应拆分检索后再汇总。"
)
_REASON_CODES = {
    "missing_entity",
    "missing_scope",
    "missing_time",
    "missing_metric",
    "coref_uncertain",
    "mixed",
}
_AMBIGUITY_REASON_LABELS = {
    "missing_entity": "缺少具体对象",
    "missing_scope": "缺少范围约束",
    "missing_time": "缺少时间范围",
    "missing_metric": "缺少指标口径",
    "coref_uncertain": "指代对象不明确",
    "mixed": "关键信息不完整",
}

_MULTI_QUERY_LABEL_TOKENS = {
    "同义词",
    "技术术语",
    "表达",
    "用户视角",
    "实际问题",
    "专家视角",
    "专业术语",
    "窄范围",
    "具体条件",
    "广范围",
    "全局概览",
    "术语化",
    "术语化查询",
    "用户表达",
    "用户表达查询",
    "范围扩展",
    "范围扩展查询",
}
_TROUBLESHOOT_KEYWORDS = (
    "怎么",
    "如何",
    "解决",
    "排查",
    "报错",
    "故障",
    "异常",
    "error",
    "failed",
    "failure",
    "troubleshoot",
    "debug",
)
_LEADING_COMPARE_PATTERNS = (
    r"^(?:请)?(?:帮我)?(?:比较|对比|compare)\s*",
)
_TRAILING_COMPARE_PATTERNS = (
    r"(?:的)?(?:区别|差异|不同点|对比|比较|优缺点)\s*$",
    r"(?:differences?|comparison)\s*$",
)
_COMPARE_KEYWORDS = (
    "compare",
    "difference",
    "differences",
    "comparison",
    "vs",
    "which",
    "better",
    "优缺点",
    "区别",
    "对比",
    "比较",
)
_MULTI_TARGET_SEPARATORS = (",", "，", " and ", " 与 ", " 和 ", "及")
_TERM_ALIAS_KEYWORDS = ("别名", "又称", "也叫", "简称", "alias", "aka")
_TAXONOMY_QUERY_KEYWORDS = (
    "主要变体",
    "常见变体",
    "变体",
    "类型",
    "分类",
    "类别",
    "列表",
    "清单",
)
_STABLE_OVERVIEW_ASK_MARKERS = ("是什么", "有哪些", "包括什么", "包括哪些")
_TAXONOMY_ASK_MARKERS = (
    "有哪些",
    "包括哪些",
    "包括什么",
    "都有哪些",
    "有哪些类型",
    "有哪些分类",
    "是什么",
)
_TAXONOMY_DRIFT_KEYWORDS = (
    "场景",
    "应用",
    "优缺点",
    "性能",
    "对比",
    "比较",
    "区别",
    "差异",
    "挑战",
    "案例",
)
_STABLE_OVERVIEW_KEYWORDS = (
    "核心组件",
    "核心模块",
    "组成部分",
    "主要变体",
    "关键步骤",
    "六步完整流程",
)
_QUESTION_PREFIX_RE = re.compile(
    r"^(?:请问|请说明|请比较|请介绍|请概述|请分析|请列出|比较|说明|介绍|概述|分析|列出|关于)\s*"
)
_ENTITY_SPLIT_RE = re.compile(r"\s*(?:和|与|及|以及|、|，|,)\s*")
_MULTI_ENTITY_SIGNAL_KEYWORDS = ("分别", "各自", "各个", "逐一")
_QUESTION_DIMENSION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("职责", ("负责什么", "职责", "核心任务", "作用", "做什么")),
    ("技术架构", ("技术架构", "采用什么技术架构", "采用什么架构", "模型架构", "架构")),
    ("挑战", ("挑战", "难点", "瓶颈")),
    ("适用场景", ("适用场景", "适用范围", "场景")),
    ("流程", ("流程", "步骤", "过程")),
)
_GUARDRAIL_TEXT_NORMALIZE_RE = re.compile(r"[\s\-‐‑‒–—―_]+")


def _normalize_reason_code(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _REASON_CODES:
            return normalized
    return "mixed"


def _looks_compare_or_multi_target(query: str) -> bool:
    lowered = query.lower()
    if any(keyword in lowered for keyword in _COMPARE_KEYWORDS):
        return True
    if any(separator in query for separator in _MULTI_TARGET_SEPARATORS):
        return True
    return (
        re.search(
            r"[\u4e00-\u9fffA-Za-z0-9\])）]\s*(?:和|与|及|以及)\s*[\u4e00-\u9fffA-Za-z0-9\[（(]",
            query,
        )
        is not None
    )


def _looks_term_alias_query(query: str) -> bool:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(keyword in lowered for keyword in _TERM_ALIAS_KEYWORDS):
        return True
    has_latin = re.search(r"[A-Za-z]", normalized) is not None
    if not has_latin:
        return False
    if re.search(r"[A-Za-z][A-Za-z0-9+_.-]*\s*[／/]\s*[A-Za-z][A-Za-z0-9+_.-]*", normalized):
        return True
    if any(token in normalized for token in ("（", "）", "(", ")")):
        return True
    return False


def _looks_taxonomy_query(query: str) -> bool:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(keyword in lowered for keyword in _COMPARE_KEYWORDS):
        return False
    if any(token in normalized for token in ("分别", "各自")):
        return False
    return any(keyword in normalized for keyword in _TAXONOMY_QUERY_KEYWORDS) and any(
        marker in normalized for marker in _TAXONOMY_ASK_MARKERS
    )


def _taxonomy_focus(text: str) -> str:
    focus = _normalize_whitespace(text)
    focus = re.sub(r"[？?]\s*$", "", focus)
    focus = re.sub(
        r"(?:的)?(?:主要|常见)?(?:变体|类型|分类|类别|列表|清单)(?:有哪些|包括哪些|包括什么|都有哪些|是什么)?\s*$",
        "",
        focus,
    )
    focus = re.sub(r"(?:有哪些|包括哪些|包括什么|都有哪些|是什么)\s*$", "", focus)
    return _normalize_whitespace(focus)


def _is_taxonomy_intent_drift_variant(candidate: str, *, original_query: str) -> bool:
    if not _looks_taxonomy_query(original_query):
        return False
    normalized = _normalize_whitespace(candidate)
    if not normalized:
        return True
    lowered = normalized.lower()
    return any(keyword in lowered for keyword in _TAXONOMY_DRIFT_KEYWORDS)


def _looks_stable_overview_query(query: str) -> bool:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return False
    if _looks_compare_or_multi_target(normalized):
        return False
    return any(keyword in normalized for keyword in _STABLE_OVERVIEW_KEYWORDS) and any(
        marker in normalized for marker in _STABLE_OVERVIEW_ASK_MARKERS
    )


def _contains_cjk(text: str) -> bool:
    return re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text) is not None


def _compact_guardrail_text(text: str) -> str:
    return _GUARDRAIL_TEXT_NORMALIZE_RE.sub("", _normalize_whitespace(text)).casefold()


def _extract_multi_target_entities_for_guardrail(question: str) -> list[str]:
    normalized = _QUESTION_PREFIX_RE.sub("", _normalize_whitespace(question))
    if not normalized or not any(
        keyword in normalized for keyword in _MULTI_ENTITY_SIGNAL_KEYWORDS
    ):
        return []

    boundary_candidates = [
        normalized.find(keyword)
        for keyword in (
            "分别",
            "各自",
            "各个",
            "逐一",
            "负责什么",
            "采用什么",
            "面临哪些",
            "技术架构",
            "挑战",
            "难点",
            "瓶颈",
            "流程",
            "步骤",
            "是什么",
            "有哪些",
        )
        if keyword in normalized
    ]
    boundary = min(boundary_candidates) if boundary_candidates else -1
    head = normalized[:boundary] if boundary > 0 else normalized

    entities: list[str] = []
    for part in _ENTITY_SPLIT_RE.split(head):
        entity = _QUESTION_PREFIX_RE.sub("", _normalize_whitespace(part).strip("：:；;，,。？? "))
        entity = re.sub(r"^(?:对比|比较)\s*", "", entity).strip()
        entity = re.sub(
            r"的?(?:职责|技术架构|架构|挑战|难点|瓶颈|适用场景|适用范围|场景|流程|步骤)$",
            "",
            entity,
        ).strip()
        entity = entity.rstrip("的").strip()
        if len(entity) < 2 or entity in {"什么", "哪些", "哪个", "哪种"}:
            continue
        if entity not in entities:
            entities.append(entity)
    return entities if len(entities) >= 2 else []


def _extract_required_dimension_keywords_for_guardrail(
    question: str,
) -> list[tuple[str, tuple[str, ...]]]:
    normalized = _normalize_whitespace(question)
    required: list[tuple[str, tuple[str, ...]]] = []
    for label, keywords in _QUESTION_DIMENSION_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            required.append((label, keywords))
    return required


def _normalize_guardrail_reason(original_query: str, candidate_query: str) -> str | None:
    original = _normalize_whitespace(original_query)
    candidate = _normalize_whitespace(candidate_query)
    if not original or not candidate or original == candidate:
        return None
    if _looks_taxonomy_query(original):
        if _contains_cjk(original) and not _contains_cjk(candidate):
            return "taxonomy_cross_language_drift"
        original_anchor_terms = [
            term for term in _TAXONOMY_QUERY_KEYWORDS if term in original
        ]
        if original_anchor_terms and not any(term in candidate for term in original_anchor_terms):
            return "taxonomy_anchor_lost"
        if any(marker in original for marker in _TAXONOMY_ASK_MARKERS) and not any(
            marker in candidate for marker in _TAXONOMY_ASK_MARKERS
        ):
            return "taxonomy_ask_lost"
        if _is_taxonomy_intent_drift_variant(candidate, original_query=original):
            return "taxonomy_intent_drift"
    if _looks_compare_or_multi_target(original):
        entities = _extract_multi_target_entities_for_guardrail(original)
        if len(entities) >= 2:
            compact_candidate = _compact_guardrail_text(candidate)
            missing_entities = [
                entity
                for entity in entities
                if _compact_guardrail_text(entity) not in compact_candidate
            ]
            if missing_entities:
                return "multi_target_entity_lost"
            required_dimensions = _extract_required_dimension_keywords_for_guardrail(original)
            if required_dimensions:
                for _, keywords in required_dimensions:
                    if not any(_compact_guardrail_text(keyword) in compact_candidate for keyword in keywords):
                        return "multi_target_dimension_lost"
    if not _looks_stable_overview_query(original):
        return None
    if _contains_cjk(original) and not _contains_cjk(candidate):
        return "stable_overview_cross_language_drift"
    original_anchor_terms = [
        term for term in _STABLE_OVERVIEW_KEYWORDS if term in original
    ]
    if original_anchor_terms and not any(term in candidate for term in original_anchor_terms):
        return "stable_overview_anchor_lost"
    if any(marker in original for marker in _STABLE_OVERVIEW_ASK_MARKERS) and not any(
        marker in candidate for marker in _STABLE_OVERVIEW_ASK_MARKERS
    ):
        return "stable_overview_ask_lost"
    return None


def _looks_explicit_decomposition_query(query: str) -> bool:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return False
    if any(token in normalized for token in ("分别", "各自")):
        return True
    if _looks_compare_or_multi_target(normalized) and any(
        token in normalized for token in ("比较", "对比", "区别", "差异", "优缺点", "取舍")
    ):
        return True
    return False


def _normalize_clarification_options(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _sanitize_query_text(str(value or ""))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        normalized.append(text)
        seen.add(key)
        if len(normalized) >= 6:
            break
    return normalized


def _build_clarification_payload(
    *,
    question: str,
    reason_code: str,
    confidence: float,
    model_reason: str | None,
    slots: Iterable[ClarificationSlotDecision] | None = None,
    suggested_answers: Iterable[str] | None = None,
) -> dict[str, object]:
    payload_slots: list[dict[str, object]] = []
    for slot in slots or []:
        key = _sanitize_query_text(slot.key)
        label = _sanitize_query_text(slot.label)
        if not key or not label:
            continue
        payload_slots.append(
            {
                "key": key,
                "label": label,
                "required": bool(slot.required),
                "options": _normalize_clarification_options(slot.options),
            }
        )
    return {
        "question": question,
        "reason_code": reason_code,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "model_reason": _normalize_whitespace(model_reason or ""),
        "slots": payload_slots,
        "suggested_answers": _normalize_clarification_options(suggested_answers or []),
    }


def _sanitize_aliases(aliases: Iterable[str], *, limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        value = _sanitize_query_text(str(alias or ""))
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        deduped.append(value)
        seen.add(key)
        if len(deduped) >= limit:
            break
    return deduped


def _sanitize_risk_flags(values: Iterable[object], *, limit: int = 8) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_whitespace(str(value or ""))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        normalized.append(text[:64])
        seen.add(key)
        if len(normalized) >= limit:
            break
    return normalized


def _sanitize_reverse_question(text: str) -> str:
    value = _normalize_single_line(text).strip("`\"' ")
    if not value:
        return ""
    if value.endswith("?"):
        value = value[:-1].rstrip()
    if value.endswith("？"):
        return value
    return f"{value.rstrip('。.!?,，；;')}？"



def _strip_list_prefix(text: str) -> str:
    return re.sub(r"^\s*(?:[-*]+|\d+[.)])\s*", "", text).strip()


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = _normalize_whitespace(item)
        if not value or value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def _render_recent_turns(turns: list[dict[str, str]] | None) -> str:
    if not isinstance(turns, list):
        return ""
    lines: list[str] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        role_raw = _normalize_whitespace(str(turn.get("role") or ""))
        text = _normalize_whitespace(str(turn.get("text") or ""))
        if not text:
            continue
        role = "user" if role_raw == "user" else "assistant" if role_raw == "assistant" else role_raw
        lines.append(f"{role}: {text}" if role else text)
    return "\n".join(lines[:12])


def _render_query_items(items: list[dict[str, object]] | None) -> list[str]:
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        query = _normalize_whitespace(str(item.get("query") or ""))
        if not query:
            continue
        kind = _normalize_whitespace(str(item.get("kind") or "")) or "other"
        lines.append(f"{index}. [{kind}] {query}")
    return lines


def _contains_coref_marker(query: str) -> bool:
    lowered = query.lower()
    if any(marker in lowered for marker in _COREF_MARKERS_ZH):
        return True
    return any(
        re.search(rf"\b{re.escape(marker)}\b", lowered) is not None
        for marker in _COREF_MARKERS_EN
    )

def _split_candidate_segments(text: str) -> list[str]:
    raw_segments = re.split(r"[，。；、,.!?;:\n]+", _normalize_whitespace(text))
    normalized: list[str] = []
    for segment in raw_segments:
        value = segment.strip(" \"'“”‘’()[]{}")
        if not value:
            continue
        if len(value) < 2 or len(value) > 48:
            continue
        normalized.append(value)
    return normalized

def _apply_coref_candidate(query: str, candidate: str) -> tuple[str, str]:
    q = _normalize_whitespace(query)
    c = _normalize_whitespace(candidate)
    rewritten = q
    replaced = False
    for marker in _COREF_MARKERS:
        if marker in _COREF_MARKERS_EN:
            pattern = re.compile(rf"\b{re.escape(marker)}\b", flags=re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(marker), flags=re.IGNORECASE)
        rewritten, count = pattern.subn(c, rewritten)
        if count > 0:
            replaced = True
    rewritten = _sanitize_query_text(rewritten)
    if replaced and rewritten:
        return rewritten, "replace_marker"
    # If marker exists but not replaced (or stripped away), prefix candidate context conservatively.
    if c and c.lower() not in q.lower():
        prefixed = _sanitize_query_text(f"{c} {q}")
        if prefixed:
            return prefixed, "prefix_candidate"
    return q, "noop"


def _rule_based_multi_query_candidates(query: str) -> list[str]:
    q = _normalize_whitespace(query)
    if not q:
        return []

    def _default_focus(text: str) -> str:
        focus = re.sub(r"^(?:请)?(?:介绍|解释|说明|分析|总结|聊聊|请问)\s*", "", text)
        focus = re.sub(r"(?:是什么|是啥|有哪些|如何|怎么做|怎么办)\s*$", "", focus)
        return _normalize_whitespace(focus) or text

    def _comparison_focus(text: str) -> str:
        focus = text
        for pattern in _LEADING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        for pattern in _TRAILING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        focus = re.sub(r"\b(?:vs|versus)\b", " ", focus, flags=re.IGNORECASE)
        focus = re.sub(r"[，,、/]+", " ", focus)
        focus = focus.replace(" 和 ", " ").replace(" 与 ", " ").replace(" 及 ", " ")
        focus = focus.replace("和", " ").replace("与", " ").replace("及", " ")
        focus = focus.replace("的", " ")
        return _normalize_whitespace(focus) or text

    lowered = q.lower()
    if _looks_taxonomy_query(q):
        focus = _taxonomy_focus(q) or _default_focus(q)
        return [
            q,
            f"{focus} 主要变体 类型 分类",
            f"{focus} 常见变体 列表",
        ]
    if _looks_compare_or_multi_target(q):
        focus = _comparison_focus(q)
        return [
            q,
            f"{focus} 原理 机制 对比",
            f"{focus} 适用场景 优缺点",
        ]
    if any(keyword in lowered for keyword in _TROUBLESHOOT_KEYWORDS):
        focus = _default_focus(q)
        return [
            q,
            f"{focus} 原因 排查",
            f"{focus} 解决方案 最佳实践",
        ]
    focus = _default_focus(q)
    return [
        q,
        f"{focus} 核心概念 定义",
        f"{focus} 应用场景 限制",
    ]


def _rule_based_decomposition_candidates(query: str) -> list[dict[str, object]]:
    q = _normalize_whitespace(query)
    if not q:
        return []

    def _clean_clause(text: str) -> str:
        clause = _normalize_whitespace(text)
        clause = clause.strip("，。；;,.!?？! ")
        clause = re.sub(r"^(?:请)?(?:帮我)?", "", clause)
        clause = re.sub(r"(?:是什么|是啥|有哪些|如何|怎么办|怎么做)\s*$", "", clause)
        return _normalize_whitespace(clause)

    def _comparison_focus(text: str) -> str:
        focus = text
        for pattern in _LEADING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        for pattern in _TRAILING_COMPARE_PATTERNS:
            focus = re.sub(pattern, "", focus, flags=re.IGNORECASE)
        focus = re.sub(r"\b(?:vs|versus)\b", " ", focus, flags=re.IGNORECASE)
        focus = re.sub(r"[，,、/]+", " ", focus)
        return _normalize_whitespace(focus)

    candidates: list[dict[str, object]] = []
    seen: set[str] = set()

    def _append(text: str, *, purpose: str, tags: list[str]) -> None:
        normalized = _clean_clause(text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(
            {
                "query": normalized,
                "purpose": purpose,
                "coverage_tags": tags,
            }
        )

    clause_split = re.split(
        r"(?:，|,)?(?:并说明|并概括|并总结|并分析|并阐述|并补充|同时说明|同时概括|以及说明|以及分析)",
        q,
        maxsplit=1,
    )
    primary_clause = clause_split[0] if clause_split else q
    secondary_clause = clause_split[1] if len(clause_split) > 1 else ""

    primary_focus = (
        _comparison_focus(primary_clause)
        if _looks_compare_or_multi_target(primary_clause)
        else primary_clause
    )
    _append(primary_focus, purpose="primary_compare", tags=["comparison"])
    if secondary_clause:
        _append(secondary_clause, purpose="secondary_clause", tags=["follow_up"])

    if len(candidates) < 2 and _looks_compare_or_multi_target(q):
        comparison_query = primary_focus or q
        _append(
            f"{comparison_query} 核心区别 对比",
            purpose="comparison_summary",
            tags=["comparison"],
        )
        _append(
            f"{comparison_query} 分别 作用 角色",
            purpose="role_split",
            tags=["multi_target"],
        )

    if len(candidates) < 2:
        fallback_focus = _clean_clause(q)
        _append(f"{fallback_focus} 子问题 1", purpose="fallback_part_1", tags=["fallback"])
        _append(f"{fallback_focus} 子问题 2", purpose="fallback_part_2", tags=["fallback"])

    normalized_specs: list[dict[str, object]] = []
    for idx, item in enumerate(candidates[:DECOMPOSITION_MAX_SUB_QUERIES], start=1):
        normalized_specs.append(
            {
                "query": item["query"],
                "priority": idx,
                "coverage_tags": item["coverage_tags"],
                "purpose": item["purpose"],
            }
        )
    return normalized_specs


def _is_label_stuffed_multi_query(candidate: str, *, original_query: str) -> bool:
    normalized_candidate = _normalize_whitespace(candidate)
    normalized_original = _normalize_whitespace(original_query)
    if not normalized_candidate or not normalized_original:
        return False
    if normalized_candidate == normalized_original:
        return False
    if not normalized_candidate.startswith(normalized_original):
        return False
    suffix = _normalize_whitespace(normalized_candidate[len(normalized_original) :])
    if not suffix:
        return False
    tokens = [token.strip() for token in re.split(r"\s+", suffix) if token.strip()]
    if not tokens:
        return False
    return all(token in _MULTI_QUERY_LABEL_TOKENS for token in tokens)


def _normalize_multi_query_variants(
    queries: Iterable[str], *, original_query: str
) -> tuple[list[str], str | None]:
    normalized: list[str] = []
    invalid_reason: str | None = None
    original = _normalize_whitespace(original_query)
    for candidate in _dedupe_keep_order(queries):
        if _is_label_stuffed_multi_query(candidate, original_query=original):
            invalid_reason = invalid_reason or "label_stuffing"
            continue
        if _is_taxonomy_intent_drift_variant(candidate, original_query=original_query):
            continue
        normalized.append(candidate)
    distinct_from_original = [
        candidate for candidate in normalized if _normalize_whitespace(candidate) != original
    ]
    if len(distinct_from_original) < 2:
        invalid_reason = invalid_reason or "insufficient_distinct_queries"
    return normalized, invalid_reason


def _coerce_fixed_multi_query_variants(
    queries: Iterable[str], *, original_query: str
) -> tuple[list[str], bool, str | None]:
    base, invalid_reason = _normalize_multi_query_variants(
        queries,
        original_query=original_query,
    )
    if len(base) >= MULTI_QUERY_FIXED_VARIANTS:
        return base[:MULTI_QUERY_FIXED_VARIANTS], False, invalid_reason

    completed = _dedupe_keep_order(
        [*base, *_rule_based_multi_query_candidates(original_query)]
    )
    if len(completed) < MULTI_QUERY_FIXED_VARIANTS:
        for idx in range(len(completed), MULTI_QUERY_FIXED_VARIANTS):
            completed.append(f"{_normalize_whitespace(original_query)} 变体{idx + 1}")
    return completed[:MULTI_QUERY_FIXED_VARIANTS], True, invalid_reason


def _normalize_hyde_documents(
    docs: Iterable[str], *, limit: int = HYDE_NUM_HYPOTHESES
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        value = _normalize_whitespace(_strip_list_prefix(str(doc or "")))
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
        if len(normalized) >= limit:
            break
    return normalized


def build_query_items(
    *,
    main_query: str,
    sub_queries: list[str] | None = None,
    sub_query_specs: list[dict[str, object]] | None = None,
    variants: list[str] | None = None,
    hyde_doc: str | None = None,
    hyde_docs: list[str] | None = None,
    hyde_note: str | None = None,
) -> list[QueryItem]:
    """Build a unified query collection for retrieval + provenance.

    - `main_query` is always retained as the first query item.
    - Sub-queries and variants can coexist (complex path keeps both).
    - HyDE is included as a *dense-only* query item by default.
    - When `hyde_docs` has multiple candidates, retrieval may aggregate embeddings.
    """

    main = _normalize_whitespace(main_query)
    if not main:
        return []

    items: list[QueryItem] = [
        {
            "kind": "main",
            "query": main,
            "use_dense": True,
            "use_bm25": True,
        }
    ]

    if sub_queries:
        specs_by_query: dict[str, dict[str, object]] = {}
        for spec in sub_query_specs or []:
            if not isinstance(spec, dict):
                continue
            query_value = _normalize_whitespace(str(spec.get("query") or ""))
            if not query_value:
                continue
            specs_by_query.setdefault(query_value.casefold(), spec)
        for idx, q in enumerate(sub_queries):
            qn = _normalize_whitespace(q)
            if qn:
                spec = specs_by_query.get(qn.casefold()) or {}
                raw_tags = (
                    spec.get("coverage_tags")
                    if isinstance(spec.get("coverage_tags"), list)
                    else []
                )
                coverage_tags = [
                    _normalize_whitespace(str(tag))
                    for tag in raw_tags
                    if _normalize_whitespace(str(tag))
                ][:6]
                priority = spec.get("priority")
                if not isinstance(priority, int):
                    priority = idx + 1
                purpose = _normalize_whitespace(str(spec.get("purpose") or ""))
                items.append(
                    {
                        "kind": "subquery",
                        "query": qn,
                        "index": idx,
                        "origin": "decomposition",
                        "subquery_id": f"sq_{idx + 1}",
                        "priority": max(1, min(int(priority), 8)),
                        "coverage_tags": coverage_tags,
                        "purpose": purpose,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )
    if variants:
        for idx, q in enumerate(variants):
            qn = _normalize_whitespace(q)
            if qn:
                items.append(
                    {
                        "kind": "variant",
                        "query": qn,
                        "index": idx,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )

    hyde_candidates: list[str] = []
    if hyde_docs:
        hyde_candidates.extend([str(value) for value in hyde_docs if str(value).strip()])
    if hyde_doc:
        hyde_candidates.append(hyde_doc)
    hyde_candidates = _normalize_hyde_documents(hyde_candidates)
    if hyde_candidates:
        hyde_item: QueryItem = {
            "kind": "hyde",
            "query": hyde_candidates[0],
            "index": 0,
            "use_dense": True,
            "use_bm25": False,
            "hyde_queries": hyde_candidates,
            "hyde_aggregation": HYDE_AGGREGATION,
        }
        if hyde_note:
            hyde_item["note"] = _normalize_whitespace(hyde_note)
        items.append(hyde_item)

    # Global dedupe to avoid repeated retrieval calls. Keep first occurrence.
    deduped: list[QueryItem] = []
    seen: set[tuple[str, bool, bool]] = set()
    for item in items:
        query = item.get("query") or ""
        use_dense = bool(item.get("use_dense", True))
        use_bm25 = bool(item.get("use_bm25", True))
        key = (query, use_dense, use_bm25)
        if query and key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


class QueryRewriteService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._prompts = get_prompt_loader()
        self._structured_chat_model: object | None = None
        self._structured_agents: dict[type[BaseModel], object] = {}

    def _get_structured_chat_model(self) -> object:
        if self._structured_chat_model is None:
            self._structured_chat_model = create_chat_model(
                settings=self._settings,
                use_previous_response_id=False,
            )
        return self._structured_chat_model

    def _get_structured_agent(self, schema: type[BaseModel]) -> object:
        agent = self._structured_agents.get(schema)
        if agent is not None:
            return agent
        agent = create_agent(
            model=self._get_structured_chat_model(),
            tools=[],
            system_prompt="",
            response_format=schema,
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
            return _AMBIGUITY_REASON_LABELS.get(
                normalized_code, _DEFAULT_AMBIGUITY_TRUE_REASON
            )
        return _DEFAULT_AMBIGUITY_FALSE_REASON

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
        heuristic_compare_or_multi_target = _looks_compare_or_multi_target(normalized_query)
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
                reasoning=_DEFAULT_COMPLEXITY_DECOMPOSITION_REASON,
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
                reasoning=_DEFAULT_COMPLEXITY_MULTI_QUERY_REASON,
                failure_reason=failure_reason,
                confidence=0.28,
                risk_flags=_sanitize_risk_flags(risk_flags),
                decision_version=COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=latency_ms,
            )
        return ComplexityRouteResult(
            strategy="direct",
            success=False,
            reasoning=_DEFAULT_COMPLEXITY_DIRECT_REASON,
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
                reasoning=_GUARDRAIL_COMPLEXITY_DECOMPOSITION_REASON,
                failure_reason=None,
                confidence=confidence,
                risk_flags=_sanitize_risk_flags(
                    [*current_risk_flags, "comparison" if is_comparison else "", "multi_target"]
                ),
                decision_version=decision_version or COMPLEXITY_CLASSIFY_DECISION_VERSION,
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
                reasoning=_GUARDRAIL_COMPLEXITY_DIRECT_REASON,
                failure_reason=None,
                confidence=confidence,
                risk_flags=_sanitize_risk_flags([*current_risk_flags, "stable_overview"]),
                decision_version=decision_version or COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=latency_ms,
            )

        return None

    async def _invoke_structured(
        self,
        *,
        agent: object,
        schema: type[BaseModel],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        _ = max_tokens
        request = {"messages": [{"role": "user", "content": user_prompt}]}
        try:
            ainvoke = getattr(agent, "ainvoke", None)
            if callable(ainvoke):
                result = await ainvoke(request)
            else:
                result = await asyncio.to_thread(agent.invoke, request)
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
            return StructuredCallResult(payload=None, success=False, reason="invalid_schema")
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
            model = self._get_structured_chat_model().bind(max_tokens=max_tokens)
            structured_model = model.with_structured_output(
                schema,
                method="function_calling",
                include_raw=True,
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
            ainvoke = getattr(structured_model, "ainvoke", None)
            if callable(ainvoke):
                result = await ainvoke(request)
            else:
                result = await asyncio.to_thread(structured_model.invoke, request)
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
        if not query.strip():
            return RewriteResult(query=query, rewritten=False, reason="empty")

        try:
            prompt = self._prompts.render_with_few_shot(prompt_key, question=query)
        except KeyError:
            return RewriteResult(query=query, rewritten=False, reason="prompt_missing")
        start_time = time.perf_counter()

        max_tokens_value = (
            int(self._settings.retrieval_query_rewrite_max_tokens)
            if max_tokens is None
            else int(max_tokens)
        )
        try:
            rewritten = await self._call_llm(prompt, max_tokens=max_tokens_value)
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
        self,
        query: str,
        *,
        enabled: bool = True,
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ) -> RewriteResult:
        """Resolve conversational references with an LLM and fail open to the original query."""
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
        structured_result = await self._call_prompt_structured(
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
            triggered = bool(payload.triggered or resolved_query != q or selected_mention)
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
                        _DEFAULT_CLARIFICATION_QUESTION
                        if needs_clarification
                        else ""
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
        self,
        query: str,
        *,
        enabled: bool = True,
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ) -> RewriteResult:
        """Backward-compatible alias for LLM-driven reference resolution."""
        return await self.resolve_reference(
            query,
            enabled=enabled,
            recent_turns=recent_turns,
            summary_text=summary_text,
            memory_snippet=memory_snippet,
        )

    async def normalize_rewrite(
        self,
        query: str,
    ) -> RewriteResult:
        """Normalize query with structured LLM output only; fail open to original query."""
        start = time.perf_counter()
        q = _sanitize_query_text(query)
        if not q:
            return RewriteResult(query=q, rewritten=False, reason="empty", latency_ms=0)

        structured_result = await self._call_prompt_structured(
            "kb_chat/normalize_query",
            schema=NormalizeDecision,
            max_tokens=320,
            question=q,
        )
        fallback_reason = structured_result.reason or "llm_failed_fail_open"
        if structured_result.success and isinstance(structured_result.payload, NormalizeDecision):
            payload = structured_result.payload
            candidate_query = _sanitize_query_text(payload.canonical_query)
            if candidate_query and bool(payload.constraint_preserved) and not bool(
                payload.drift_risk
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

    async def plan_retrieval_budget(
        self,
        *,
        question: str,
        normalized_query: str,
        complexity_level: str,
        query_items: list[dict[str, object]] | None,
        retry_count: int,
        failure_reason: str,
        max_top_k: int,
        fallback_budget: dict[str, int],
    ) -> RetrievalPlanResult:
        """Plan retrieval budget with an LLM and fail open to the supplied fallback budget."""
        start = time.perf_counter()
        normalized_items = query_items if isinstance(query_items, list) else []
        query_count = max(
            1,
            sum(
                1
                for item in normalized_items
                if isinstance(item, dict)
                and _normalize_whitespace(str(item.get("query") or ""))
            ),
        )
        structured_result = await self._call_prompt_structured(
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
                min(int(payload.rerank_input_limit), max(max_global_candidates, safe_max_top_k * 4)),
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
            success=bool(structured_result.success and structured_result.payload is not None),
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
        self,
        query: str,
        *,
        enabled: bool | None = None,
        coref_meta: dict[str, object] | None = None,
    ) -> AmbiguityResult:
        """Model-driven ambiguity decision with guardrail fallback."""
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
                question=_DEFAULT_CLARIFICATION_QUESTION,
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
            prompt = self._prompts.render_with_few_shot(
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
            structured_result = await self._invoke_model_structured(
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
            model_reason = self._resolve_ambiguity_business_reason(
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
                    question_text = _DEFAULT_CLARIFICATION_QUESTION
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
            ambiguous = self._is_ambiguous_heuristic(q)
            failure_reason = structured_result.reason or "model_failed_guardrail_fallback"
            if ambiguous:
                reason_code = (
                    "coref_uncertain" if coref_needs_clarification else "mixed"
                )
                confidence = 0.35
                model_reason = self._resolve_ambiguity_business_reason(
                    ambiguous=True,
                    model_reason=None,
                    reason_code=reason_code,
                )
                reason = model_reason
                clarification_payload = _build_clarification_payload(
                    question=_DEFAULT_CLARIFICATION_QUESTION,
                    reason_code=reason_code,
                    confidence=confidence,
                    model_reason=model_reason,
                )
                reverse_question = str(clarification_payload.get("question") or "")
            else:
                model_reason = self._resolve_ambiguity_business_reason(
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
        self,
        query: str,
        *,
        reason: str,
        hint: str | None = None,
        enabled: bool = True,
    ) -> RewriteResult:
        """Transform query for retry (rewrite/expand), with safe fallback."""
        if not enabled:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="disabled",
                latency_ms=0,
            )

        structured_result = await self._call_prompt_structured(
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

        # Reuse existing retrieval rewrite behavior as a low-risk fallback.
        fallback = await self.rewrite(query)
        # If fallback succeeded but didn't change, still keep transform surface explicit.
        if fallback.reason is None:
            fallback.reason = structured_result.reason or "fallback_rewrite"
        return fallback

    async def resolve_merge_context_conflict(
        self,
        *,
        question: str,
        summary_text: str,
        memory_snippet: str,
    ) -> MergeContextResolutionResult:
        """Resolve conflict between summary and memory content for context merge."""
        structured_result = await self._call_prompt_structured(
            "kb_chat/context_merge",
            schema=MergeContextResolutionDecision,
            max_tokens=192,
            question=_normalize_whitespace(question),
            summary_text=_normalize_whitespace(summary_text),
            memory_snippet=_normalize_whitespace(memory_snippet),
        )
        payload = structured_result.payload
        if (
            structured_result.success
            and isinstance(payload, MergeContextResolutionDecision)
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
        self,
        query: str,
        *,
        recall_risk: str | None = None,
        has_multi_target: bool = False,
        is_comparison: bool = False,
    ) -> ComplexityRouteResult:
        """Decide preprocess routing strategy."""
        start = time.perf_counter()
        q = _normalize_whitespace(query)
        if not q:
            return ComplexityRouteResult(
                strategy="direct",
                success=False,
                reasoning=_DEFAULT_COMPLEXITY_DIRECT_REASON,
                confidence=0.0,
                risk_flags=[],
                decision_version=COMPLEXITY_CLASSIFY_DECISION_VERSION,
                latency_ms=0,
            )

        try:
            prompt = self._prompts.render_with_few_shot(
                "kb_chat/complexity_classify",
                question=q,
                recall_risk=(recall_risk or "unknown"),
                has_multi_target=bool(has_multi_target),
                is_comparison=bool(is_comparison),
            )
        except KeyError:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return self._fallback_complexity_route(
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
            return self._fallback_complexity_route(
                query=q,
                recall_risk=recall_risk,
                has_multi_target=has_multi_target,
                is_comparison=is_comparison,
                failure_reason="prompt_error",
                latency_ms=latency_ms,
            )

        structured_result = await self._invoke_model_structured(
            schema=ComplexityDecision,
            user_prompt=prompt,
            max_tokens=256,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, ComplexityDecision)
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
            guarded_result = self._apply_complexity_guardrail(
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
        return self._fallback_complexity_route(
            query=q,
            recall_risk=recall_risk,
            has_multi_target=has_multi_target,
            is_comparison=is_comparison,
            failure_reason=structured_result.reason or "llm_failed_fallback_direct",
            latency_ms=latency_ms,
        )

    async def decompose(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        """Decompose query into sub-questions via structured LLM output only."""
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

        structured_result = await self._call_prompt_structured(
            "kb_chat/decomposition",
            schema=DecompositionDecision,
            max_tokens=256,
            question=q,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, DecompositionDecision)
        ):
            payload = structured_result.payload
            spec_queries = [
                _normalize_whitespace(str(spec.get("query") or ""))
                for spec in payload.sub_query_specs
                if isinstance(spec, dict)
            ]
            sub_queries = _dedupe_keep_order(
                [*spec_queries, *payload.sub_queries]
            )[:DECOMPOSITION_MAX_SUB_QUERIES]
            if len(sub_queries) >= 2:
                latency_ms = int((time.perf_counter() - start) * 1000)
                normalized_specs: list[dict[str, object]] = []
                for idx, q in enumerate(sub_queries):
                    matched = next(
                        (
                            spec
                            for spec in payload.sub_query_specs
                            if isinstance(spec, dict)
                            and _normalize_whitespace(str(spec.get("query") or ""))
                            == q
                        ),
                        None,
                    )
                    if isinstance(matched, dict):
                        raw_tags = (
                            matched.get("coverage_tags")
                            if isinstance(matched.get("coverage_tags"), list)
                            else []
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
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        """Generate exactly 3 multi-query variants (LLM-first with safe fallback)."""
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

        structured_result = await self._call_prompt_structured(
            "kb_chat/multi_query",
            schema=MultiQueryDecision,
            max_tokens=256,
            question=q,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, MultiQueryDecision)
        ):
            fixed_variants, completed, invalid_reason = _coerce_fixed_multi_query_variants(
                structured_result.payload.queries,
                original_query=q,
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
        self,
        query: str,
    ) -> QueryListResult:
        """HyDE generator (LLM-first with safe fallback)."""
        start = time.perf_counter()
        q = _normalize_whitespace(query)
        if not q:
            return QueryListResult(queries=[], success=False, reason="empty", latency_ms=0)

        structured_result = await self._call_prompt_structured(
            "kb_chat/hyde",
            schema=HyDEBatchDecision,
            max_tokens=768,
            question=q,
            num_hypotheses=HYDE_NUM_HYPOTHESES,
        )
        if structured_result.success and isinstance(
            structured_result.payload, HyDEBatchDecision
        ):
            docs = _normalize_hyde_documents(
                structured_result.payload.hypothetical_documents,
                limit=HYDE_NUM_HYPOTHESES,
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

    def _is_ambiguous_heuristic(self, query: str) -> bool:
        q = _normalize_whitespace(query)
        if not q:
            return True
        if len(q) <= 2:
            return True
        # Guardrail only: short query + coreference markers is likely ambiguous.
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
        """Call prompt and parse structured output via with_structured_output(..., method="function_calling")."""
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
        for attempt in range(1, STRUCTURED_CALL_MAX_ATTEMPTS + 1):
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
                or attempt >= STRUCTURED_CALL_MAX_ATTEMPTS
                or reason not in STRUCTURED_CALL_RETRYABLE_REASONS
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
