"""Helpers for structured KB answer paragraphs."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.agents.kb_chat_agentic.schemas import AnswerParagraph

_CITATION_LABEL_RE = re.compile(r"\[(S\d+)\]", re.IGNORECASE)
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([，。！？；：,.!?;:])")
_MULTI_BLANK_LINE_RE = re.compile(r"\n{3,}")
_TERMINAL_PUNCTUATION = ("。", "！", "？", "!", "?", "；", ";", "：", ":")
_LEADING_PUNCTUATION = tuple("，。！？；：,.!?;:)]】）】")


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _clean_text(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", cleaned)
    cleaned = _MULTI_BLANK_LINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def _strip_citation_labels(text: str) -> str:
    return _clean_text(_CITATION_LABEL_RE.sub("", text))


def _rebuild_text_from_claims(paragraph: AnswerParagraph) -> str:
    rebuilt_parts: list[str] = []
    for claim in paragraph.claims:
        claim_text = _strip_citation_labels(claim.claim_text)
        if not claim_text:
            continue
        if not rebuilt_parts:
            rebuilt_parts.append(claim_text)
            continue
        if rebuilt_parts[-1].endswith(_TERMINAL_PUNCTUATION) or claim_text.startswith(
            _LEADING_PUNCTUATION
        ):
            rebuilt_parts.append(claim_text)
        else:
            rebuilt_parts.append(f"\n{claim_text}")
    return _clean_text("".join(rebuilt_parts))


def recalculate_paragraph_citation_ids(
    paragraph: AnswerParagraph | dict[str, object],
) -> AnswerParagraph:
    parsed = AnswerParagraph.model_validate(paragraph)
    if not parsed.claims:
        return parsed.model_copy(
            update={"citation_ids": _dedupe_preserve_order(parsed.citation_ids)}
        )

    citation_ids = _dedupe_preserve_order(
        citation_id
        for claim in parsed.claims
        for citation_id in claim.supporting_citation_ids
    )
    return parsed.model_copy(update={"citation_ids": citation_ids})


def prune_unsupported_auxiliary_claims(
    paragraphs: Iterable[AnswerParagraph | dict[str, object]],
) -> list[AnswerParagraph]:
    pruned: list[AnswerParagraph] = []
    for paragraph in paragraphs:
        parsed = AnswerParagraph.model_validate(paragraph)
        kept_claims = [
            claim
            for claim in parsed.claims
            if not (
                claim.role == "auxiliary" and claim.support_status == "unsupported"
            )
        ]
        updated = parsed.model_copy(update={"claims": kept_claims})
        if len(kept_claims) != len(parsed.claims):
            text = _rebuild_text_from_claims(updated)
        else:
            text = _clean_text(parsed.text)
        updated = updated.model_copy(update={"text": text})
        pruned.append(recalculate_paragraph_citation_ids(updated))
    return pruned


def render_answer_paragraphs(
    paragraphs: Iterable[AnswerParagraph | dict[str, object]],
) -> str:
    rendered: list[str] = []
    for paragraph in paragraphs:
        parsed = recalculate_paragraph_citation_ids(AnswerParagraph.model_validate(paragraph))
        text = _strip_citation_labels(parsed.text)
        suffix = "".join(f"[{citation_id}]" for citation_id in parsed.citation_ids)
        if text or suffix:
            rendered.append(f"{text}{suffix}" if text else suffix)
    return "\n\n".join(rendered)
