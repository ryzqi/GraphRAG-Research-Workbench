"""KB Chat answer subgraph 共享辅助。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from pydantic import ValidationError

from app.agents.kb_chat_agentic.schemas import AnswerParagraph, AnswerRenderMeta
from app.agents.kb_chat_agentic_state import AnswerCommitInput
from app.core.settings import Settings
from app.services.evidence_guardrails import (
    extract_citation_label_occurrences,
    is_kb_refusal_answer,
    normalize_citation_label,
)
from app.services.kb_answer_paragraphs import normalize_answer_text_variants
from app.services.kb_evidence import resolve_structured_evidence

_REPAIRABLE_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
    "unsupported_claims",
}
_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
_INLINE_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,128})\]|【([^【】\n]{1,128})】")
_REVIEW_CHECKS: tuple[Literal["citation", "answer"], ...] = (
    "citation",
    "answer",
)
StateView = Mapping[str, object]


class KbChatAnswerSubgraphContext(TypedDict, total=False):
    """从父图透传的类型化运行时上下文。"""

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


def _get_loop_counts(state: StateView) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _current_review_round(state: StateView) -> int:
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
        return "END"

    loop_counts = _get_loop_counts(state)
    max_total_rounds = int(getattr(settings, "kb_chat_max_total_rounds", 3))
    max_retrieval_retries = int(getattr(settings, "kb_chat_max_retrieval_retries", 2))
    if loop_counts["total_rounds"] >= max_total_rounds:
        return "force_exit"
    if loop_counts["retrieval_retries"] >= max_retrieval_retries:
        return "force_exit"
    return "transform_query"


def _merge_stage_summary(
    state: StateView,
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
    state: StateView,
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


def _resolve_query_text(state: StateView) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("resolved_query")
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


def _resolve_allowed_citation_labels(
    state: StateView,
    *,
    final_context: str,
) -> tuple[dict[str, str], str, str]:
    evidence_items, citation_catalog, structured_context = resolve_structured_evidence(
        state.get("evidence_items"),
        citation_catalog=state.get("citation_catalog"),
    )
    if citation_catalog:
        labels = {
            f"[{citation_id}]".casefold(): f"[{citation_id}]"
            for citation_id in citation_catalog
        }
        return labels, "citation_catalog", structured_context or final_context
    return _extract_evidence_labels(final_context), "final_context", final_context


def _extract_citations(answer: str) -> list[str]:
    if not answer:
        return []
    return [f"[{label}]" for label in extract_citation_label_occurrences(answer)]


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


def _normalize_citation_id(value: object) -> str:
    return normalize_citation_label(_as_str(value))


def _normalize_citation_label(value: object) -> str:
    citation_id = _normalize_citation_id(value)
    return f"[{citation_id}]" if citation_id else ""


def _ordered_unique_paragraph_ids(
    paragraphs: list[AnswerParagraph],
    paragraph_ids: set[str],
) -> list[str]:
    return [
        paragraph.paragraph_id
        for paragraph in paragraphs
        if paragraph.paragraph_id in paragraph_ids
    ]


def _load_answer_paragraphs(
    state: StateView,
    *,
    draft_answer: str = "",
) -> list[AnswerParagraph]:
    raw_paragraphs = state.get("answer_paragraphs")
    paragraphs: list[AnswerParagraph] = []
    if isinstance(raw_paragraphs, list):
        for raw in raw_paragraphs:
            try:
                paragraphs.append(AnswerParagraph.model_validate(raw))
            except ValidationError:
                continue
        return paragraphs
    if not draft_answer:
        return []
    fallback_citation_ids = [
        citation_id
        for citation_id in (
            _normalize_citation_id(raw_label)
            for raw_label in _extract_citations(draft_answer)
        )
        if citation_id
    ]
    try:
        return [
            AnswerParagraph(
                paragraph_id="p1",
                text=draft_answer,
                citation_ids=fallback_citation_ids,
                claims=[],
                review_status="passed",
            )
        ]
    except ValidationError:
        return []


def _resolve_unsupported_scope(
    paragraphs: list[AnswerParagraph],
) -> tuple[str, list[str]]:
    main_ids: set[str] = set()
    auxiliary_ids: set[str] = set()
    for paragraph in paragraphs:
        has_main_unsupported = any(
            claim.role == "main" and claim.support_status == "unsupported"
            for claim in paragraph.claims
        )
        has_auxiliary_unsupported = any(
            claim.role == "auxiliary" and claim.support_status == "unsupported"
            for claim in paragraph.claims
        )
        if has_main_unsupported:
            main_ids.add(paragraph.paragraph_id)
        if has_auxiliary_unsupported:
            auxiliary_ids.add(paragraph.paragraph_id)
    if main_ids and auxiliary_ids:
        scope = "mixed"
    elif main_ids:
        scope = "main"
    elif auxiliary_ids:
        scope = "auxiliary_only"
    else:
        scope = "none"
    return scope, _ordered_unique_paragraph_ids(paragraphs, main_ids | auxiliary_ids)


def _build_paragraph_review_counts(
    paragraphs: list[AnswerParagraph],
    *,
    failed_paragraph_ids: set[str],
) -> dict[str, int]:
    total = len(paragraphs)
    failed = min(len(failed_paragraph_ids), total)
    return {
        "total": total,
        "passed": max(total - failed, 0),
        "failed": failed,
    }


def _build_review_details(
    paragraphs: list[AnswerParagraph],
    *,
    failed_paragraph_ids: set[str],
    repair_target_ids: set[str] | None = None,
    unsupported_scope: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    repair_target_ids = repair_target_ids or set()
    details: dict[str, object] = {
        "paragraph_review_counts": _build_paragraph_review_counts(
            paragraphs,
            failed_paragraph_ids=failed_paragraph_ids,
        ),
        "repair_target_count": len(repair_target_ids),
        "unsupported_scope": unsupported_scope or "none",
    }
    if isinstance(extra, dict):
        details.update(extra)
    return details


def _build_answer_render_meta_from_paragraphs(
    paragraphs: list[AnswerParagraph],
) -> dict[str, Any]:
    citation_ids: list[str] = []
    claim_count = 0
    for paragraph in paragraphs:
        claim_count += len(paragraph.claims)
        citation_ids.extend(paragraph.citation_ids)
    return AnswerRenderMeta(
        paragraph_count=len(paragraphs),
        claim_count=claim_count,
        citation_count=len(dict.fromkeys(citation_ids)),
        citation_mode="paragraph_aggregate",
    ).model_dump()


def _normalize_repaired_paragraphs(
    paragraphs: list[AnswerParagraph],
) -> list[AnswerParagraph]:
    normalized: list[AnswerParagraph] = []
    for paragraph in paragraphs:
        has_unsupported = any(
            claim.support_status == "unsupported" for claim in paragraph.claims
        )
        review_status = "needs_repair" if has_unsupported else "passed"
        normalized.append(paragraph.model_copy(update={"review_status": review_status}))
    return normalized


def _format_paragraph_review_payload(paragraphs: list[AnswerParagraph]) -> str:
    if not paragraphs:
        return "（无可用段落元数据）"
    blocks: list[str] = []
    for paragraph in paragraphs:
        claim_lines = [
            (
                f"- role={claim.role}; support_status={claim.support_status}; "
                f"claim={claim.claim_text}; supporting_citation_ids={list(claim.supporting_citation_ids)}"
            )
            for claim in paragraph.claims
        ] or ["- （无 claims）"]
        blocks.append(
            "\n".join(
                [
                    f"paragraph_id={paragraph.paragraph_id}",
                    f"text={paragraph.text}",
                    f"citation_ids={list(paragraph.citation_ids)}",
                    "claims:",
                    *claim_lines,
                ]
            )
        )
    return "\n\n".join(blocks)


def _is_refusal_like_paragraph_text(text: str) -> bool:
    normalized = _as_str(text).strip()
    if not normalized:
        return False
    return is_kb_refusal_answer(normalized)


def _strip_inline_citations(text: str) -> str:
    if not text:
        return ""
    stripped = _INLINE_CITATION_RE.sub("", normalize_answer_text_variants(text))
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _compact_answer_coverage_text(text: str) -> str:
    normalized = normalize_answer_text_variants(_strip_inline_citations(text))
    return re.sub(r"[\s\-‐‑‒–—―_]+", "", normalized).casefold()


