from __future__ import annotations

from collections import Counter
import re
from typing import Any

from pydantic import ValidationError

from app.agents.kb_chat_agentic.schemas import ContextCompressDecision

_BLANK_LINE_RE = re.compile(r"\n{2,}")
_MARKDOWN_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_MARKDOWN_ITALIC_RE = re.compile(
    r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)|(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)"
)
_MARKDOWN_CODE_RE = re.compile(r"`([^`]+)`")
_LEADING_MARKDOWN_PREFIX_RE = re.compile(r"^(?:[-*+]\s+|\d+\.\s+|#{1,6}\s+)")
_PAREN_LATIN_TERM_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9][A-Za-z0-9\- ]{1,})\)")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_markdown_inline(text: str) -> str:
    normalized = text
    for _ in range(3):
        updated = _MARKDOWN_BOLD_RE.sub(r"\2", normalized)
        updated = _MARKDOWN_ITALIC_RE.sub(
            lambda match: (match.group(1) or match.group(2) or "").strip(),
            updated,
        )
        updated = _MARKDOWN_CODE_RE.sub(r"\1", updated)
        if updated == normalized:
            break
        normalized = updated
    return normalized


def _normalize_verbatim_text(text: str) -> str:
    normalized = _normalize_newlines(text)
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    normalized = normalized.replace("�", "")
    for char in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"):
        normalized = normalized.replace(char, "-")
    normalized = normalized.replace("…", "...")
    normalized = _strip_markdown_inline(normalized)

    lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        line = _LEADING_MARKDOWN_PREFIX_RE.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        lines.append(line)
    normalized = "\n".join(lines)
    normalized = _BLANK_LINE_RE.sub("\n\n", normalized)
    return normalized.strip()


def _ordered_verbatim_subset(parts: list[str], source: str) -> bool:
    cursor = 0
    for part in parts:
        position = source.find(part, cursor)
        if position < 0:
            return False
        cursor = position + len(part)
    return True


def _is_verbatim_subset(candidate_excerpt: str, source_excerpt: str) -> bool:
    candidate = _normalize_verbatim_text(candidate_excerpt)
    source = _normalize_verbatim_text(source_excerpt)
    if not candidate or not source:
        return False
    if candidate in source:
        return True
    if candidate.endswith("..."):
        truncated_candidate = candidate.rstrip(".").rstrip()
        if len(truncated_candidate) >= 12 and truncated_candidate in source:
            return True

    paragraph_parts = [part for part in _BLANK_LINE_RE.split(candidate) if part.strip()]
    if len(paragraph_parts) > 1 and _ordered_verbatim_subset(paragraph_parts, source):
        return True

    line_parts = [line for line in candidate.split("\n") if line.strip()]
    return len(line_parts) > 1 and _ordered_verbatim_subset(line_parts, source)


def _recoverable_verbatim_parts(candidate_excerpt: str) -> list[str]:
    candidate = _normalize_verbatim_text(candidate_excerpt)
    if not candidate:
        return []
    candidate = re.sub(r"(?<=[。！？.!?])\s+(?=\d+\.\s*)", "\n", candidate)
    candidate = re.sub(r"\s+-\s+(?=[^\s-])", "\n", candidate)
    parts: list[str] = []
    for raw_part in candidate.split("\n"):
        part = _LEADING_MARKDOWN_PREFIX_RE.sub("", raw_part).strip()
        if len(part) < 12:
            continue
        parts.append(part)
    return parts


def _recover_source_excerpt(candidate_excerpt: str, source_excerpt: str) -> str | None:
    source = _normalize_verbatim_text(source_excerpt)
    if not source:
        return None
    matched_parts = [
        part
        for part in _recoverable_verbatim_parts(candidate_excerpt)
        if part in source
    ]
    if len(matched_parts) >= 2:
        return source_excerpt
    return None


def _match_selected_excerpt_to_source(
    candidate_excerpt: str,
    source_excerpt: str,
) -> str | None:
    excerpt = _normalize_newlines(candidate_excerpt).strip()
    if not excerpt or not source_excerpt:
        return None
    if _is_verbatim_subset(excerpt, source_excerpt):
        return excerpt
    recovered_excerpt = _recover_source_excerpt(excerpt, source_excerpt)
    if recovered_excerpt is None:
        return None
    return _normalize_newlines(recovered_excerpt).strip()


def _question_requests_challenge_list(question: str) -> bool:
    normalized = _normalize_newlines(question).strip()
    if not normalized or "挑战" not in normalized:
        return False
    return any(token in normalized for token in ("哪些", "各自", "分别", "都有哪些"))


def _question_requests_original_terms(question: str) -> bool:
    normalized = _normalize_newlines(question).strip()
    if not normalized:
        return False
    return any(
        token in normalized
        for token in ("技术架构", "模型名称", "组件名称", "术语", "名词清单")
    )


def _extract_parenthesized_original_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in _PAREN_LATIN_TERM_RE.finditer(_normalize_newlines(text)):
        term = match.group(1).strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _should_expand_selected_excerpt_to_source(
    *,
    question: str,
    candidate_excerpt: str,
    source_excerpt: str,
    duplicate_selection: bool,
) -> bool:
    if not source_excerpt:
        return False

    normalized_candidate = _normalize_verbatim_text(candidate_excerpt)
    normalized_source = _normalize_verbatim_text(source_excerpt)
    if (
        not normalized_candidate
        or not normalized_source
        or normalized_candidate == normalized_source
        or normalized_candidate not in normalized_source
    ):
        return False

    if duplicate_selection:
        return True
    if _question_requests_challenge_list(question) and "挑战" in source_excerpt:
        return True
    if _question_requests_original_terms(question):
        required_terms = _extract_parenthesized_original_terms(source_excerpt)
        normalized_candidate_fold = normalized_candidate.casefold()
        if required_terms and any(
            term.casefold() not in normalized_candidate_fold for term in required_terms
        ):
            return True
    return False


def _normalize_selected_context_compress_items(
    *,
    question: str,
    rebuilt_items: list[dict[str, Any]],
    source_items_by_citation: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    citation_counts = Counter(
        str(item.get("citation_id") or "").strip().upper()
        for item in rebuilt_items
        if isinstance(item, dict)
    )
    normalized: list[dict[str, Any]] = []
    expanded_citations: set[str] = set()

    for item in rebuilt_items:
        citation_id = str(item.get("citation_id") or "").strip().upper()
        source_item = source_items_by_citation.get(citation_id)
        source_excerpt = (
            _normalize_newlines(str(source_item.get("excerpt") or "")).strip()
            if isinstance(source_item, dict)
            else ""
        )
        candidate_excerpt = _normalize_newlines(str(item.get("excerpt") or "")).strip()
        should_expand = _should_expand_selected_excerpt_to_source(
            question=question,
            candidate_excerpt=candidate_excerpt,
            source_excerpt=source_excerpt,
            duplicate_selection=citation_counts[citation_id] > 1,
        )
        if should_expand and isinstance(source_item, dict):
            if citation_id in expanded_citations:
                continue
            normalized.append(
                {
                    **source_item,
                    "citation_id": citation_id,
                    "excerpt": source_excerpt,
                }
            )
            expanded_citations.add(citation_id)
            continue
        normalized.append(item)
    return normalized


def _find_unique_matching_evidence_source(
    *,
    candidate_excerpt: str,
    current_evidence_items: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], str] | None:
    matches: list[tuple[str, dict[str, Any], str]] = []
    for source_item in current_evidence_items:
        citation_id = str(source_item.get("citation_id") or "").strip().upper()
        if not citation_id:
            continue
        matched_excerpt = _match_selected_excerpt_to_source(
            candidate_excerpt,
            str(source_item.get("excerpt") or ""),
        )
        if matched_excerpt is None:
            continue
        matches.append((citation_id, source_item, matched_excerpt))
        if len(matches) > 1:
            return None
    if len(matches) != 1:
        return None
    return matches[0]


def _coerce_context_compress_decision(
    value: object,
) -> tuple[ContextCompressDecision | None, str | None]:
    if isinstance(value, ContextCompressDecision):
        return value, None
    try:
        return ContextCompressDecision.model_validate(value), None
    except ValidationError:
        return None, "invalid_schema"
