"""KB Chat answer subgraph 审查辅助。"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any

from langchain.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import ValidationError

from app.agents.kb_chat_agentic.reflection import (
    _extract_question_entities,
    _extract_required_dimensions,
    _extract_required_term_map,
)
from app.agents.kb_chat_agentic.schemas import AnswerParagraph, AnswerReviewSubDecision
from app.agents.kb_chat_agentic_state import AnswerReviewFuseInput, AnswerReviewRun
from app.services.kb_answer_paragraphs import (
    normalize_answer_text_variants,
    prune_unsupported_auxiliary_claims,
    render_answer_paragraphs,
)
from app.services.query_rewrite_service import coerce_structured_result_payload

from .answer_subgraph_shared import (
    StateView,
    _REPAIRABLE_FAILURE_REASONS,
    _as_str,
    _build_answer_render_meta_from_paragraphs,
    _build_review_details,
    _compact_answer_coverage_text,
    _current_review_round,
    _extract_citations,
    _is_refusal_like_paragraph_text,
    _load_answer_paragraphs,
    _normalize_citation_id,
    _normalize_citation_label,
    _normalize_repaired_paragraphs,
    _ordered_unique_paragraph_ids,
    _resolve_unsupported_scope,
    _strip_inline_citations,
)

def _detect_multi_entity_answer_gap(
    *,
    question: str,
    draft: str,
    paragraphs: list[AnswerParagraph],
) -> dict[str, object] | None:
    entities = _extract_question_entities(question)
    if len(entities) < 2:
        return None

    answer_body = "\n".join(
        paragraph.text.strip()
        for paragraph in paragraphs
        if paragraph.text and paragraph.text.strip()
    ).strip()
    if not answer_body:
        answer_body = draft
    compact_answer = _compact_answer_coverage_text(answer_body)
    missing_entities = [
        entity
        for entity in entities
        if _compact_answer_coverage_text(entity) not in compact_answer
    ]
    if not missing_entities:
        return None

    paragraph_ids = [
        paragraph.paragraph_id
        for paragraph in paragraphs
        if isinstance(paragraph.paragraph_id, str) and paragraph.paragraph_id.strip()
    ]
    return {
        "reason": "incomplete",
        "missing_entities": missing_entities,
        "required_dimensions": _extract_required_dimensions(question),
        "affected_paragraph_ids": paragraph_ids[-1:] if paragraph_ids else [],
        "coverage_guardrail": "multi_entity_entities",
    }


def _detect_required_original_term_gap(
    *,
    question: str,
    draft: str,
    paragraphs: list[AnswerParagraph],
    final_context: str,
) -> dict[str, object] | None:
    normalized_question = _as_str(question).strip()
    if not normalized_question or not final_context:
        return None

    required_dimensions = _extract_required_dimensions(normalized_question)
    requires_original_terms = any(
        dimension in required_dimensions for dimension in ("职责", "技术架构")
    ) or any(
        keyword in normalized_question
        for keyword in ("模型名称", "组件名称", "术语", "名词清单")
    )
    if not requires_original_terms:
        return None

    entities = _extract_question_entities(normalized_question)
    if len(entities) < 2:
        return None

    required_term_map = _extract_required_term_map(
        entities,
        final_context=final_context,
        required_dimensions=required_dimensions,
    )
    if not required_term_map:
        return None

    answer_body = "\n".join(
        paragraph.text.strip()
        for paragraph in paragraphs
        if paragraph.text and paragraph.text.strip()
    ).strip()
    if not answer_body:
        answer_body = draft
    compact_answer = _compact_answer_coverage_text(answer_body)
    if not compact_answer:
        return None

    missing_terms: dict[str, list[str]] = {}
    affected_ids: list[str] = []
    for entity in entities:
        compact_entity = _compact_answer_coverage_text(entity)
        if not compact_entity or compact_entity not in compact_answer:
            continue
        terms = required_term_map.get(entity) or []
        missing_for_entity = [
            term
            for term in terms
            if _compact_answer_coverage_text(term) not in compact_answer
        ]
        if not missing_for_entity:
            continue
        missing_terms[entity] = missing_for_entity
        for paragraph in paragraphs:
            paragraph_id = _as_str(paragraph.paragraph_id).strip()
            if not paragraph_id:
                continue
            compact_paragraph = _compact_answer_coverage_text(paragraph.text)
            if compact_entity in compact_paragraph:
                affected_ids.append(paragraph_id)

    if not missing_terms:
        return None

    ordered_affected_ids = list(dict.fromkeys(affected_ids))
    if not ordered_affected_ids:
        ordered_affected_ids = [
            paragraph.paragraph_id
            for paragraph in paragraphs
            if isinstance(paragraph.paragraph_id, str)
            and paragraph.paragraph_id.strip()
        ][-1:]

    return {
        "reason": "incomplete",
        "missing_terms": missing_terms,
        "required_dimensions": required_dimensions,
        "affected_paragraph_ids": ordered_affected_ids,
        "repair_target_count": len(ordered_affected_ids),
        "coverage_guardrail": "required_original_terms",
    }


def _project_answer_text_to_paragraphs(answer: str) -> list[AnswerParagraph]:
    cleaned_answer = normalize_answer_text_variants(_as_str(answer)).strip()
    if not cleaned_answer:
        return []
    raw_blocks = [
        block.strip() for block in re.split(r"\n\s*\n", cleaned_answer) if block.strip()
    ]
    if not raw_blocks:
        raw_blocks = [cleaned_answer]
    paragraphs: list[AnswerParagraph] = []
    for index, block in enumerate(raw_blocks, start=1):
        citation_ids = [
            citation_id
            for citation_id in (
                _normalize_citation_id(raw_label)
                for raw_label in _extract_citations(block)
            )
            if citation_id
        ]
        paragraphs.append(
            AnswerParagraph(
                paragraph_id=f"p{index}",
                text=_strip_inline_citations(block),
                citation_ids=list(dict.fromkeys(citation_ids)),
                claims=[],
                review_status="passed",
            )
        )
    return paragraphs


def _review_paragraph_citations(
    paragraphs: list[AnswerParagraph],
    *,
    allowed_labels: dict[str, str],
) -> dict[str, object]:
    allowed_by_id = {
        _normalize_citation_id(label).casefold(): label
        for label in allowed_labels.values()
        if _normalize_citation_id(label)
    }
    all_citations: list[str] = []
    valid_citations: set[str] = set()
    invalid_citations: set[str] = set()
    missing_citations: list[str] = []
    citation_mismatches: list[str] = []
    failed_ids: set[str] = set()
    metadata_incomplete = False

    for paragraph in paragraphs:
        paragraph_valid_labels: set[str] = set()
        paragraph_has_citations = False
        for raw_citation_id in paragraph.citation_ids:
            normalized_id = _normalize_citation_id(raw_citation_id)
            if not normalized_id:
                continue
            paragraph_has_citations = True
            label = f"[{normalized_id}]"
            all_citations.append(label)
            canonical = allowed_by_id.get(normalized_id.casefold())
            if canonical is None:
                invalid_citations.add(label)
                failed_ids.add(paragraph.paragraph_id)
            else:
                valid_citations.add(canonical)
                paragraph_valid_labels.add(canonical)

        main_claims = [
            claim
            for claim in paragraph.claims
            if claim.role == "main" and claim.claim_text.strip()
        ]
        if (
            paragraph.text.strip()
            and not paragraph_has_citations
            and not main_claims
            and not _is_refusal_like_paragraph_text(paragraph.text)
        ):
            missing_citations.append(paragraph.text.strip())
            failed_ids.add(paragraph.paragraph_id)
            continue
        citable_main_claims = []
        for claim in main_claims:
            supporting_labels = {
                normalized
                for normalized in (
                    _normalize_citation_label(raw_support_id)
                    for raw_support_id in claim.supporting_citation_ids
                )
                if normalized
            }
            if (
                claim.support_status in {"supported", "weak_supported"}
                and supporting_labels
            ):
                citable_main_claims.append((claim, supporting_labels))
        if not main_claims and paragraph.text.strip() and paragraph_has_citations:
            metadata_incomplete = True
        if not paragraph_has_citations and citable_main_claims:
            for claim, _ in citable_main_claims:
                missing_citations.append(claim.claim_text)
            failed_ids.add(paragraph.paragraph_id)
            continue
        for claim, supporting_labels in citable_main_claims:
            if not paragraph_has_citations:
                missing_citations.append(claim.claim_text)
                failed_ids.add(paragraph.paragraph_id)
                continue
            if not supporting_labels.issubset(paragraph_valid_labels):
                citation_mismatches.append(claim.claim_text)
                failed_ids.add(paragraph.paragraph_id)
        if main_claims and not citable_main_claims and paragraph_has_citations:
            metadata_incomplete = True

    unsupported_scope, _ = _resolve_unsupported_scope(paragraphs)
    if invalid_citations:
        reason = "invalid_citations"
        passed = False
    elif missing_citations:
        reason = "missing_citations"
        passed = False
    elif citation_mismatches:
        reason = "citation_mismatch"
        passed = False
    else:
        reason = "passed"
        passed = True

    affected_ids = _ordered_unique_paragraph_ids(paragraphs, failed_ids)
    repair_target_ids = set(affected_ids) if not passed else set()
    return {
        "passed": passed,
        "reason": reason,
        "all_citations": all_citations,
        "valid_citations": valid_citations,
        "invalid_citations": invalid_citations,
        "missing_citations": list(dict.fromkeys(missing_citations))[:3],
        "citation_mismatches": list(dict.fromkeys(citation_mismatches))[:3],
        "affected_paragraph_ids": affected_ids,
        "needs_llm": bool(paragraphs) and passed and metadata_incomplete,
        "details": _build_review_details(
            paragraphs,
            failed_paragraph_ids=failed_ids,
            repair_target_ids=repair_target_ids,
            unsupported_scope=unsupported_scope,
            extra={
                "invalid_citation_count": len(invalid_citations),
                "missing_citation_count": len(list(dict.fromkeys(missing_citations))),
                "citation_mismatch_count": len(
                    list(dict.fromkeys(citation_mismatches))
                ),
            },
        ),
    }


def _resolve_answer_review_details(
    paragraphs: list[AnswerParagraph],
    *,
    reason: str,
    unsupported_claims: list[str],
) -> tuple[list[str], dict[str, object]]:
    unsupported_scope, unsupported_ids = _resolve_unsupported_scope(paragraphs)
    failed_ids: set[str] = {
        paragraph.paragraph_id
        for paragraph in paragraphs
        if paragraph.review_status != "passed"
        or any(claim.support_status == "unsupported" for claim in paragraph.claims)
    }
    affected_ids = unsupported_ids if reason == "unsupported_claims" else []
    repair_target_ids = (
        set(unsupported_ids) if unsupported_scope == "auxiliary_only" else set()
    )
    details = _build_review_details(
        paragraphs,
        failed_paragraph_ids=failed_ids,
        repair_target_ids=repair_target_ids,
        unsupported_scope=unsupported_scope,
        extra={"unsupported_claim_count": len(unsupported_claims)},
    )
    return affected_ids, details


def _extract_run_details(run: Mapping[str, object]) -> dict[str, Any]:
    raw = run.get("details")
    return raw if isinstance(raw, dict) else {}


def _extract_run_affected_paragraph_ids(run: Mapping[str, object]) -> set[str]:
    raw = run.get("affected_paragraph_ids")
    if not isinstance(raw, list):
        return set()
    return {
        _as_str(paragraph_id).strip()
        for paragraph_id in raw
        if _as_str(paragraph_id).strip()
    }


def _coalesce_paragraph_summary(
    citation: Mapping[str, object],
    answer: Mapping[str, object],
) -> tuple[dict[str, int], int, str]:
    answer_details = _extract_run_details(answer)
    citation_details = _extract_run_details(citation)

    def _counts_from(details: dict[str, Any]) -> dict[str, int]:
        raw = details.get("paragraph_review_counts")
        if not isinstance(raw, dict):
            return {"total": 0, "passed": 0, "failed": 0}
        return {
            "total": int(raw.get("total") or 0),
            "passed": int(raw.get("passed") or 0),
            "failed": int(raw.get("failed") or 0),
        }

    answer_counts = _counts_from(answer_details)
    citation_counts = _counts_from(citation_details)
    affected_ids = _extract_run_affected_paragraph_ids(
        citation
    ) | _extract_run_affected_paragraph_ids(answer)
    total = max(answer_counts["total"], citation_counts["total"], len(affected_ids))
    failed = max(answer_counts["failed"], citation_counts["failed"], len(affected_ids))
    counts = {
        "total": total,
        "passed": max(total - failed, 0),
        "failed": failed,
    }
    answer_repair_target = answer_details.get("repair_target_count")
    citation_repair_target = citation_details.get("repair_target_count")
    repair_target_count = max(
        int(answer_repair_target) if isinstance(answer_repair_target, (int, float)) else 0,
        int(citation_repair_target)
        if isinstance(citation_repair_target, (int, float))
        else 0,
    )
    unsupported_scope_summary = (
        _as_str(
            answer_details.get(
                "unsupported_scope",
                citation_details.get("unsupported_scope", "none"),
            )
        ).strip()
        or "none"
    )
    return counts, repair_target_count, unsupported_scope_summary


def _is_repairable_review_failure(
    *,
    reason: str,
    citation: Mapping[str, object],
    answer: Mapping[str, object],
) -> bool:
    if reason == "incomplete":
        coverage_guardrail = _as_str(
            _extract_run_details(answer).get("coverage_guardrail")
        ).strip()
        return coverage_guardrail == "required_original_terms"
    if reason not in _REPAIRABLE_FAILURE_REASONS:
        return False
    if reason != "unsupported_claims":
        return True
    unsupported_scope = _as_str(
        _extract_run_details(answer).get("unsupported_scope")
    ).strip()
    return unsupported_scope == "auxiliary_only"


def _resolve_answer_review_details_from_state(state: StateView) -> dict[str, Any]:
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    review_breakdown_raw = reflection_obj.get("review_breakdown")
    review_breakdown = review_breakdown_raw if isinstance(review_breakdown_raw, dict) else {}
    answer_check_raw = review_breakdown.get("answer")
    answer_check = answer_check_raw if isinstance(answer_check_raw, dict) else {}
    details = answer_check.get("details")
    if isinstance(details, dict):
        return details
    return {}


def _resolve_unsupported_scope_from_state(state: StateView) -> str:
    review_details = _resolve_answer_review_details_from_state(state)
    unsupported_scope = _as_str(review_details.get("unsupported_scope")).strip()
    if unsupported_scope:
        return unsupported_scope

    stage_summaries = state.get("stage_summaries")
    answer_review_summary = (
        answer_review
        if isinstance(stage_summaries, dict)
        and isinstance((answer_review := stage_summaries.get("answer_review")), dict)
        else {}
    )
    return _as_str(answer_review_summary.get("unsupported_scope_summary")).strip()


def _count_unsupported_auxiliary_claims(paragraphs: list[AnswerParagraph]) -> int:
    return sum(
        1
        for paragraph in paragraphs
        for claim in paragraph.claims
        if claim.role == "auxiliary" and claim.support_status == "unsupported"
    )


def _maybe_repair_auxiliary_only_paragraphs(
    state: StateView,
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    reason = _as_str(reflection_obj.get("reason")).strip()
    if reason != "unsupported_claims":
        return None

    unsupported_scope = _resolve_unsupported_scope_from_state(state)
    if unsupported_scope != "auxiliary_only":
        return None

    paragraphs = _load_answer_paragraphs(
        state,
        draft_answer=_as_str(state.get("draft_answer")).strip(),
    )
    if not paragraphs:
        return None

    pruned = prune_unsupported_auxiliary_claims(paragraphs)
    normalized = _normalize_repaired_paragraphs(pruned)
    serialized = [paragraph.model_dump() for paragraph in normalized]
    render_meta = _build_answer_render_meta_from_paragraphs(normalized)
    repaired_answer = render_answer_paragraphs(normalized)
    return serialized, render_meta, repaired_answer


def _project_repair_candidate(
    candidate: str,
    *,
    allowed_labels: dict[str, str],
) -> tuple[
    list[dict[str, Any]] | None,
    dict[str, Any] | None,
    str | None,
    str | None,
]:
    projected_paragraphs = _project_answer_text_to_paragraphs(candidate)
    if not projected_paragraphs:
        return None, None, None, "repair_projection_empty"

    paragraph_review = _review_paragraph_citations(
        projected_paragraphs,
        allowed_labels=allowed_labels,
    )
    review_reason = _as_str(paragraph_review.get("reason")).strip()
    if review_reason != "passed":
        return None, None, None, f"repair_projection_{review_reason or 'failed'}"

    normalized_answer = render_answer_paragraphs(projected_paragraphs)
    if not normalized_answer:
        return None, None, None, "repair_projection_empty"

    return (
        [paragraph.model_dump() for paragraph in projected_paragraphs],
        _build_answer_render_meta_from_paragraphs(projected_paragraphs),
        normalized_answer,
        "",
    )


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
    try:
        structured_model = chat_model.with_structured_output(
            AnswerReviewSubDecision,
            method="function_calling",
            include_raw=True,
        )
        result = await structured_model.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, _classify_structured_error(exc)
    payload, reason = coerce_structured_result_payload(
        result=result,
        schema=AnswerReviewSubDecision,
    )
    if payload is None:
        return None, reason
    if isinstance(payload, AnswerReviewSubDecision):
        return payload, None
    try:
        payload = AnswerReviewSubDecision.model_validate(payload)
    except ValidationError:
        return None, "invalid_schema"
    return payload, None


def _resolve_subcheck(
    state: AnswerReviewFuseInput,
    check: str,
) -> AnswerReviewRun | None:
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


