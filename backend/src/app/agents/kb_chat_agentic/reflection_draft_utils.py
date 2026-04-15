"""KB Chat agentic reflection 草稿辅助。"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from langchain.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.services.kb_answer_paragraphs import (
    normalize_answer_text_variants,
    recalculate_paragraph_citation_ids,
    render_answer_paragraphs,
)
from app.services.query_rewrite_service import coerce_structured_result_payload
from app.services.query_rewrite_text import (
    _extract_multi_target_entities_for_guardrail,
    _extract_required_dimension_keywords_for_guardrail,
)
from app.services.streaming import extract_answer_text

from .reflection_shared import (
    _EVIDENCE_LINE_RE,
    _INLINE_CITATION_RE,
    _LATIN_TERM_RE,
    _RESPONSIBILITY_LABEL_RE,
    _RESPONSIBILITY_STAGE_RE,
    _as_str,
)
from .schemas import AnswerParagraph, AnswerRenderMeta, DraftAnswerDecision

def _extract_question_entities(question: str) -> list[str]:
    return _extract_multi_target_entities_for_guardrail(question)


def _extract_required_dimensions(question: str) -> list[str]:
    return [
        label
        for label, _ in _extract_required_dimension_keywords_for_guardrail(question)
    ]


def _extract_required_term_map(
    entities: list[str],
    *,
    final_context: str,
    required_dimensions: list[str] | None = None,
) -> dict[str, list[str]]:
    if not entities or not final_context:
        return {}

    required_dimensions = required_dimensions or []
    blocks: list[str] = []
    current_block: list[str] = []
    for raw_line in _as_str(final_context).splitlines():
        line = _as_str(raw_line)
        if _EVIDENCE_LINE_RE.match(line):
            if current_block:
                block = "\n".join(current_block).strip()
                if block:
                    blocks.append(block)
            current_block = [line]
            continue
        if current_block:
            current_block.append(line)
    if current_block:
        block = "\n".join(current_block).strip()
        if block:
            blocks.append(block)
    if not blocks:
        blocks = [_as_str(final_context).strip()]

    def _normalize_required_term(term: object) -> str:
        normalized = _as_str(term)
        normalized = normalized.replace("**", "").replace("__", "").strip()
        normalized = re.split(r"[（(]", normalized, maxsplit=1)[0]
        normalized = re.split(r"[。；;，,\n]", normalized, maxsplit=1)[0]
        normalized = normalized.strip(" -*_`：:、")
        return normalized

    def _append_term(terms: list[str], term: object) -> None:
        normalized = _normalize_required_term(term)
        if not normalized or normalized in terms:
            return
        terms.append(normalized)

    def _extract_block_terms(block: str) -> list[str]:
        terms: list[str] = []
        lines = [line.strip() for line in _as_str(block).splitlines() if line.strip()]
        if "职责" in required_dimensions:
            for line in lines:
                if "核心任务" in line or "职责" in line or "作用" in line:
                    for match in _RESPONSIBILITY_LABEL_RE.finditer(line):
                        _append_term(terms, match.group(1))
                if "负责" in line:
                    for match in _RESPONSIBILITY_STAGE_RE.finditer(line):
                        parenthetical = _normalize_required_term(match.group(2))
                        if parenthetical:
                            _append_term(terms, parenthetical)
                            continue
                        stage_or_label = _normalize_required_term(match.group(1))
                        if stage_or_label and (
                            stage_or_label.endswith("阶段") or len(stage_or_label) <= 6
                        ):
                            _append_term(terms, stage_or_label)
        if "技术架构" in required_dimensions:
            for line in lines:
                if not any(
                    keyword in line
                    for keyword in ("技术架构", "架构", "采用", "结构", "编码器")
                ):
                    continue
                for match in _LATIN_TERM_RE.finditer(line):
                    _append_term(terms, match.group(1))
        return terms

    term_map: dict[str, list[str]] = {}
    for entity in entities:
        entity_key = re.sub(r"\s+", "", entity).casefold()
        terms: list[str] = []
        relevant_blocks = [
            block
            for block in blocks
            if entity_key and entity_key in re.sub(r"\s+", "", block).casefold()
        ]
        if not relevant_blocks and len(blocks) == len(entities):
            entity_index = entities.index(entity)
            if 0 <= entity_index < len(blocks):
                relevant_blocks = [blocks[entity_index]]
        for block in relevant_blocks:
            for term in _extract_block_terms(block):
                _append_term(terms, term)
        if terms:
            term_map[entity] = terms[:4]
    return term_map


def _build_answer_coverage_hint(question: str, final_context: str = "") -> str:
    entities = _extract_question_entities(question)
    if len(entities) < 2:
        return ""

    dimensions = _extract_required_dimensions(question)
    dimension_text = " / ".join(dimensions) if dimensions else "问题要求的关键信息"
    required_terms = _extract_required_term_map(
        entities,
        final_context=final_context,
        required_dimensions=dimensions,
    )
    lines = ["覆盖清单："]
    for entity in entities:
        line = f"- {entity}: {dimension_text}"
        terms = required_terms.get(entity)
        if terms:
            line += f"；必须保留原始名词：{' / '.join(terms)}"
        lines.append(line)
    lines.extend(
        [
            "额外约束：",
            "- 必须按上面的实体 × 维度逐项覆盖；若某个维度无证据，只能说明该维度缺证，不得把整实体写成“资料不足”。",
            "- 只要参考内容中已经出现某实体或其原始术语，就不得声称“参考内容未提供该实体信息”。",
            "- 对技术架构、职责标签或阶段名类问题，必须显式保留参考内容中的原始名词或标签。",
        ]
    )
    return "\n".join(lines)


def _compact_answer_coverage_text(text: str) -> str:
    normalized = normalize_answer_text_variants(_as_str(text))
    return re.sub(r"[\s\-‐‑‒–—―_]+", "", normalized).casefold()


def _detect_draft_coverage_gap(
    *,
    question: str,
    draft: str,
    final_context: str,
) -> dict[str, object] | None:
    entities = _extract_question_entities(question)
    if len(entities) < 2:
        return None

    compact_answer = _compact_answer_coverage_text(draft)
    missing_entities = [
        entity
        for entity in entities
        if _compact_answer_coverage_text(entity) not in compact_answer
    ]
    if missing_entities:
        return {
            "reason": "incomplete",
            "missing_entities": missing_entities,
            "required_dimensions": _extract_required_dimensions(question),
            "coverage_guardrail": "multi_entity_entities",
        }

    required_dimensions = _extract_required_dimensions(question)
    requires_original_terms = any(
        dimension in required_dimensions for dimension in ("职责", "技术架构")
    ) or any(
        keyword in _as_str(question)
        for keyword in ("模型名称", "组件名称", "术语", "名词清单")
    )
    if not requires_original_terms:
        return None

    required_term_map = _extract_required_term_map(
        entities,
        final_context=final_context,
        required_dimensions=required_dimensions,
    )
    if not required_term_map:
        return None

    missing_terms: dict[str, list[str]] = {}
    for entity in entities:
        compact_entity = _compact_answer_coverage_text(entity)
        if compact_entity not in compact_answer:
            continue
        terms = required_term_map.get(entity) or []
        missing_for_entity = [
            term
            for term in terms
            if _compact_answer_coverage_text(term) not in compact_answer
        ]
        if missing_for_entity:
            missing_terms[entity] = missing_for_entity
    if not missing_terms:
        return None
    return {
        "reason": "incomplete",
        "missing_terms": missing_terms,
        "required_dimensions": required_dimensions,
        "coverage_guardrail": "required_original_terms",
    }


def _format_draft_coverage_gap(gap: dict[str, object] | None) -> str:
    if not isinstance(gap, dict) or not gap:
        return ""
    lines = ["当前草稿存在以下覆盖缺口："]
    missing_entities = gap.get("missing_entities")
    if isinstance(missing_entities, list) and missing_entities:
        lines.append(
            f"- 缺少实体覆盖：{' / '.join(_as_str(entity) for entity in missing_entities)}"
        )
    missing_terms = gap.get("missing_terms")
    if isinstance(missing_terms, dict):
        for entity, terms in missing_terms.items():
            if not isinstance(terms, list) or not terms:
                continue
            lines.append(
                f"- {_as_str(entity)} 缺少原始名词：{' / '.join(_as_str(term) for term in terms)}"
            )
    return "\n".join(lines)


async def _attempt_local_plain_text_draft_repair(
    *,
    chat_model: BaseChatModel,
    system_prompt: str,
    question: str,
    final_context: str,
    coverage_block: str,
    draft: str,
    coverage_gap: dict[str, object],
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    gap_block = _format_draft_coverage_gap(coverage_gap)
    repair_user = (
        "请修复下面这份回答草稿，仅输出最终答案正文。\n"
        "要求：\n"
        "1) 必须按实体 × 维度逐项覆盖问题要求的信息；\n"
        "2) 若参考内容已出现某实体或术语，不得把该实体整体写成“资料不足”或“未提供”；\n"
        "3) 对技术架构、职责标签或阶段名类问题，必须显式保留参考内容中的原始名词或标签；\n"
        "4) 仅使用参考内容中的事实，并在每段结尾保留有效 [Sx] 聚合引用；\n"
        "5) 不要输出 JSON、代码块或额外解释。\n\n"
        f"{gap_block}\n\n"
        f"{coverage_block}"
        f"问题：{question}\n\n"
        f"参考内容：\n{final_context}\n\n"
        f"原回答：\n{draft}"
    )
    try:
        repair_model = chat_model.bind(max_tokens=1024)
        repair_msg = await repair_model.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=repair_user)]
        )
        candidate = extract_answer_text(getattr(repair_msg, "content", "")).strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        return None
    if not candidate:
        return None

    projected = _project_plain_text_answer_to_paragraphs(
        candidate,
        allowed_citation_ids=_extract_allowed_citation_ids(final_context),
    )
    if not projected:
        return None

    repaired_payloads = [paragraph.model_dump() for paragraph in projected]
    repaired_render_meta = _build_answer_render_meta(projected)
    repaired_draft = render_answer_paragraphs(repaired_payloads).strip()
    if (
        _detect_draft_coverage_gap(
            question=question,
            draft=repaired_draft,
            final_context=final_context,
        )
        is not None
    ):
        return None
    return repaired_payloads, repaired_render_meta, repaired_draft


def _coerce_draft_answer_decision(
    payload: object,
) -> tuple[DraftAnswerDecision | None, str | None]:
    if payload is None:
        return None, "empty_structured_response"
    try:
        decision = (
            payload
            if isinstance(payload, DraftAnswerDecision)
            else DraftAnswerDecision.model_validate(payload)
        )
    except Exception:
        return None, "structured_parse_failed"
    if not decision.paragraphs:
        return decision, "empty_structured_paragraphs"
    return decision, None


def _merge_draft_structured_reason(
    *,
    payload_reason: str | None,
    decision_reason: str | None,
) -> str | None:
    if decision_reason is None:
        return payload_reason
    if (
        payload_reason
        in {"invalid_schema", "structured_parse_failed", "multiple_structured_outputs"}
        and decision_reason == "empty_structured_response"
    ):
        return payload_reason
    return decision_reason or payload_reason


def _should_retry_draft_structured(reason: str | None) -> bool:
    return reason in {
        "structured_invoke_failed",
        "empty_structured_response",
        "invalid_schema",
        "structured_parse_failed",
        "multiple_structured_outputs",
    }


def _can_project_plain_text_after_structured_failure(reason: str | None) -> bool:
    return reason in {
        "empty_structured_paragraphs",
        "empty_structured_response",
        "invalid_schema",
        "structured_parse_failed",
        "multiple_structured_outputs",
    }


def _build_draft_retry_chat_model(*, settings: Settings) -> BaseChatModel | Any | None:
    try:
        retry_model = create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        )
    except Exception:
        return None
    return retry_model


async def _invoke_draft_structured(
    *,
    chat_model: BaseChatModel,
    messages: list[SystemMessage | HumanMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str | None]:
    structured_reason: str | None = None
    paragraph_payloads: list[dict[str, Any]] = []
    render_meta = _build_answer_render_meta([])
    draft = ""

    try:
        structured_model = chat_model.with_structured_output(
            DraftAnswerDecision,
            method="function_calling",
            include_raw=True,
        )
        result = await structured_model.ainvoke(messages)
        payload, payload_reason = coerce_structured_result_payload(
            result=result,
            schema=DraftAnswerDecision,
        )
        decision, decision_reason = _coerce_draft_answer_decision(payload)
        structured_reason = _merge_draft_structured_reason(
            payload_reason=payload_reason,
            decision_reason=decision_reason,
        )
        if decision is not None:
            paragraphs = _normalize_answer_paragraphs(
                [
                    AnswerParagraph.model_validate(paragraph)
                    for paragraph in decision.paragraphs
                ]
            )
            paragraph_payloads = [paragraph.model_dump() for paragraph in paragraphs]
            render_meta = _build_answer_render_meta(paragraphs)
            draft = render_answer_paragraphs(paragraph_payloads).strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        structured_reason = "structured_invoke_failed"

    return paragraph_payloads, render_meta, draft, structured_reason


def _normalize_answer_paragraphs(
    paragraphs: list[AnswerParagraph],
) -> list[AnswerParagraph]:
    normalized: list[AnswerParagraph] = []
    seen_ids: set[str] = set()
    for index, paragraph in enumerate(paragraphs, start=1):
        paragraph_id = paragraph.paragraph_id.strip() or f"p{index}"
        if paragraph_id in seen_ids:
            paragraph_id = f"p{index}"
        seen_ids.add(paragraph_id)
        normalized.append(
            recalculate_paragraph_citation_ids(
                paragraph.model_copy(update={"paragraph_id": paragraph_id})
            )
        )
    return normalized


def _build_answer_render_meta(
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


def _extract_allowed_citation_ids(final_context: str) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for match in _EVIDENCE_LINE_RE.finditer(final_context or ""):
        citation_id = _as_str(match.group(1)).strip()
        if citation_id:
            allowed.setdefault(citation_id.casefold(), citation_id)
    return allowed


def _extract_inline_citation_ids(text: str) -> list[str]:
    normalized = normalize_answer_text_variants(_as_str(text))
    return [
        _as_str(match.group(1) or match.group(2)).strip()
        for match in _INLINE_CITATION_RE.finditer(normalized)
        if _as_str(match.group(1) or match.group(2)).strip()
    ]


def _strip_inline_citations(text: str) -> str:
    stripped = _INLINE_CITATION_RE.sub(
        "", normalize_answer_text_variants(_as_str(text))
    )
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _project_plain_text_answer_to_paragraphs(
    answer: str,
    *,
    allowed_citation_ids: dict[str, str],
) -> list[AnswerParagraph]:
    cleaned_answer = normalize_answer_text_variants(_as_str(answer)).strip()
    if not cleaned_answer:
        return []

    raw_blocks = [
        block.strip() for block in re.split(r"\n\s*\n", cleaned_answer) if block.strip()
    ]
    if not raw_blocks:
        raw_blocks = [cleaned_answer]
    merged_blocks: list[str] = []
    index = 0
    while index < len(raw_blocks):
        block = raw_blocks[index]
        current_citations = _extract_inline_citation_ids(block)
        if (
            not current_citations
            and index + 1 < len(raw_blocks)
            and _extract_inline_citation_ids(raw_blocks[index + 1])
        ):
            merged_blocks.append(f"{block}\n\n{raw_blocks[index + 1]}")
            index += 2
            continue
        merged_blocks.append(block)
        index += 1

    paragraphs: list[AnswerParagraph] = []
    for index, block in enumerate(merged_blocks, start=1):
        citation_ids: list[str] = []
        for citation_id in _extract_inline_citation_ids(block):
            canonical = allowed_citation_ids.get(citation_id.casefold())
            if canonical and canonical not in citation_ids:
                citation_ids.append(canonical)
        text = _strip_inline_citations(block)
        if not text and not citation_ids:
            continue
        paragraphs.append(
            AnswerParagraph(
                paragraph_id=f"p{index}",
                text=text,
                citation_ids=citation_ids,
                claims=[],
                review_status="passed",
            )
        )
    return paragraphs

