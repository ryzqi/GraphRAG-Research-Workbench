from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from app.agents.kb_chat_agentic.schemas import ClarificationSlotDecision
from app.utils.text_sanitization import sanitize_visible_text
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
_LEADING_COMPARE_PATTERNS = (r"^(?:请)?(?:帮我)?(?:比较|对比|compare)\s*",)
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
    if re.search(
        r"[A-Za-z][A-Za-z0-9+_.-]*\s*[／/]\s*[A-Za-z][A-Za-z0-9+_.-]*", normalized
    ):
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
        entity = _QUESTION_PREFIX_RE.sub(
            "", _normalize_whitespace(part).strip("：:；;，,。？? ")
        )
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


def _normalize_guardrail_reason(
    original_query: str, candidate_query: str
) -> str | None:
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
        if original_anchor_terms and not any(
            term in candidate for term in original_anchor_terms
        ):
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
            required_dimensions = _extract_required_dimension_keywords_for_guardrail(
                original
            )
            if required_dimensions:
                for _, keywords in required_dimensions:
                    if not any(
                        _compact_guardrail_text(keyword) in compact_candidate
                        for keyword in keywords
                    ):
                        return "multi_target_dimension_lost"
    if not _looks_stable_overview_query(original):
        return None
    if _contains_cjk(original) and not _contains_cjk(candidate):
        return "stable_overview_cross_language_drift"
    original_anchor_terms = [
        term for term in _STABLE_OVERVIEW_KEYWORDS if term in original
    ]
    if original_anchor_terms and not any(
        term in candidate for term in original_anchor_terms
    ):
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
        token in normalized
        for token in ("比较", "对比", "区别", "差异", "优缺点", "取舍")
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
        role = (
            "user"
            if role_raw == "user"
            else "assistant"
            if role_raw == "assistant"
            else role_raw
        )
        lines.append(f"{role}: {text}" if role else text)
    return "\n".join(lines[:12])


def _render_query_items(items: Sequence[Mapping[str, object]] | None) -> list[str]:
    if items is None:
        return []
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
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
    # 若标记存在但未被替换（或被清理掉），则保守地在前面补上候选上下文。
    if c and c.lower() not in q.lower():
        prefixed = _sanitize_query_text(f"{c} {q}")
        if prefixed:
            return prefixed, "prefix_candidate"
    return q, "noop"


