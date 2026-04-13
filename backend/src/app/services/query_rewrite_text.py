from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from app.agents.kb_chat_agentic.schemas import ClarificationSlotDecision
from app.config.policy_loader import load_search_policy
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

_LEADING_COMPARE_PATTERNS = (r"^(?:请)?(?:帮我)?(?:比较|对比|compare)\s*",)
_TRAILING_COMPARE_PATTERNS = (
    r"(?:的)?(?:区别|差异|不同点|对比|比较|优缺点)\s*$",
    r"(?:differences?|comparison)\s*$",
)
_QUESTION_PREFIX_RE = re.compile(
    r"^(?:请问|请说明|请比较|请介绍|请概述|请分析|请列出|比较|说明|介绍|概述|分析|列出|关于)\s*"
)
_ENTITY_SPLIT_RE = re.compile(r"\s*(?:和|与|及|以及|、|，|,)\s*")
_GUARDRAIL_TEXT_NORMALIZE_RE = re.compile(r"[\s\-‐‑‒–—―_]+")


def _query_planning_policy():
    return load_search_policy().query_planning


def _coref_markers_zh() -> tuple[str, ...]:
    return tuple(_query_planning_policy().coref_markers_zh)


def _coref_markers_en() -> tuple[str, ...]:
    return tuple(_query_planning_policy().coref_markers_en)


def _coref_markers() -> tuple[str, ...]:
    return tuple(
        sorted([*_coref_markers_zh(), *_coref_markers_en()], key=len, reverse=True)
    )


def _compare_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().compare_keywords)


def _multi_target_separators() -> tuple[str, ...]:
    return tuple(_query_planning_policy().multi_target_separators)


def _term_alias_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().term_alias_keywords)


def _taxonomy_query_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().taxonomy_query_keywords)


def _stable_overview_ask_markers() -> tuple[str, ...]:
    return tuple(_query_planning_policy().stable_overview_ask_markers)


def _taxonomy_ask_markers() -> tuple[str, ...]:
    return tuple(_query_planning_policy().taxonomy_ask_markers)


def _taxonomy_drift_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().taxonomy_drift_keywords)


def _stable_overview_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().stable_overview_keywords)


def _multi_entity_signal_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().multi_entity_signal_keywords)


def _question_dimension_keywords() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (label, tuple(keywords))
        for label, keywords in _query_planning_policy().question_dimension_keywords.items()
    )


def _decomposition_max_sub_queries() -> int:
    return int(_query_planning_policy().decomposition_max_sub_queries)


def _multi_query_fixed_variants() -> int:
    return int(_query_planning_policy().multi_query_fixed_variants)


def _hyde_num_hypotheses() -> int:
    return int(_query_planning_policy().hyde_num_hypotheses)


def _hyde_aggregation() -> str:
    return _normalize_whitespace(_query_planning_policy().hyde_aggregation).lower()


def _hyde_regenerate_on_retry() -> bool:
    return bool(_query_planning_policy().hyde_regenerate_on_retry)


def _structured_call_max_attempts() -> int:
    return int(_query_planning_policy().structured_call_max_attempts)


def _structured_call_retryable_reasons() -> frozenset[str]:
    return frozenset(_query_planning_policy().structured_call_retryable_reasons)


def _default_clarification_question() -> str:
    return _query_planning_policy().default_clarification_question


def _default_ambiguity_reason(*, ambiguous: bool) -> str:
    policy = _query_planning_policy()
    if ambiguous:
        return policy.default_ambiguity_true_reason
    return policy.default_ambiguity_false_reason


def _resolve_ambiguity_reason_label(reason_code: str) -> str | None:
    normalized_code = _normalize_reason_code(reason_code)
    return _query_planning_policy().ambiguity_reason_labels.get(normalized_code)


def _default_complexity_reason(strategy: str) -> str:
    normalized_strategy = _normalize_whitespace(strategy).lower()
    policy = _query_planning_policy()
    if normalized_strategy == "decomposition":
        return policy.default_complexity_decomposition_reason
    if normalized_strategy in {"multi_query", "generate_variants"}:
        return policy.default_complexity_multi_query_reason
    return policy.default_complexity_direct_reason


def _guardrail_complexity_reason(strategy: str) -> str:
    normalized_strategy = _normalize_whitespace(strategy).lower()
    policy = _query_planning_policy()
    if normalized_strategy == "decomposition":
        return policy.guardrail_complexity_decomposition_reason
    return policy.guardrail_complexity_direct_reason


def _multi_query_label_tokens() -> set[str]:
    return set(_query_planning_policy().multi_query_label_tokens)


def _troubleshoot_keywords() -> tuple[str, ...]:
    return tuple(_query_planning_policy().troubleshoot_keywords)


def _normalize_reason_code(value: object) -> str:
    valid_reason_codes = set(_query_planning_policy().ambiguity_reason_labels.keys())
    valid_reason_codes.add("mixed")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in valid_reason_codes:
            return normalized
    return "mixed"


def _looks_compare_or_multi_target(query: str) -> bool:
    lowered = query.lower()
    if any(keyword in lowered for keyword in _compare_keywords()):
        return True
    if any(separator in query for separator in _multi_target_separators()):
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
    if any(keyword in lowered for keyword in _term_alias_keywords()):
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
    if any(keyword in lowered for keyword in _compare_keywords()):
        return False
    if any(token in normalized for token in ("分别", "各自")):
        return False
    return any(keyword in normalized for keyword in _taxonomy_query_keywords()) and any(
        marker in normalized for marker in _taxonomy_ask_markers()
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
    return any(keyword in lowered for keyword in _taxonomy_drift_keywords())


def _looks_stable_overview_query(query: str) -> bool:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return False
    if _looks_compare_or_multi_target(normalized):
        return False
    return any(keyword in normalized for keyword in _stable_overview_keywords()) and any(
        marker in normalized for marker in _stable_overview_ask_markers()
    )


def _contains_cjk(text: str) -> bool:
    return re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text) is not None


def _compact_guardrail_text(text: str) -> str:
    return _GUARDRAIL_TEXT_NORMALIZE_RE.sub("", _normalize_whitespace(text)).casefold()


def _extract_multi_target_entities_for_guardrail(question: str) -> list[str]:
    normalized = _QUESTION_PREFIX_RE.sub("", _normalize_whitespace(question))
    if not normalized or not any(
        keyword in normalized for keyword in _multi_entity_signal_keywords()
    ):
        return []

    boundary_candidates = [
        normalized.find(keyword)
        for keyword in (
            *_multi_entity_signal_keywords(),
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
    for label, keywords in _question_dimension_keywords():
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
            term for term in _taxonomy_query_keywords() if term in original
        ]
        if original_anchor_terms and not any(
            term in candidate for term in original_anchor_terms
        ):
            return "taxonomy_anchor_lost"
        if any(marker in original for marker in _taxonomy_ask_markers()) and not any(
            marker in candidate for marker in _taxonomy_ask_markers()
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
        term for term in _stable_overview_keywords() if term in original
    ]
    if original_anchor_terms and not any(
        term in candidate for term in original_anchor_terms
    ):
        return "stable_overview_anchor_lost"
    if any(marker in original for marker in _stable_overview_ask_markers()) and not any(
        marker in candidate for marker in _stable_overview_ask_markers()
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
    if any(marker in lowered for marker in _coref_markers_zh()):
        return True
    return any(
        re.search(rf"\b{re.escape(marker)}\b", lowered) is not None
        for marker in _coref_markers_en()
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
    english_markers = set(_coref_markers_en())
    for marker in _coref_markers():
        if marker in english_markers:
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


