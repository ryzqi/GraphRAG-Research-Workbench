"""Evidence/citation guardrails for KB chat."""

from __future__ import annotations

import re

_CITATION_BLOCK_RE = re.compile(
    r"\[([^\[\]\n]{1,128})\]|【([^【】\n]{1,128})】"
)
_CITATION_SPLIT_RE = re.compile(r"[,\uFF0C;\uFF1B\u3001]+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_STABLE_CITATION_ID_RE = re.compile(r"^S[1-9]\d*$", re.IGNORECASE)
_NO_ANSWER_PREFIXES = (
    "根据现有资料无法回答该问题",
    "基于当前信息仍无法稳定回答该问题",
)
_RETRY_EXHAUSTED_NO_ANSWER = "基于当前信息仍无法稳定回答该问题（已停止重试）。"


def _collapse_spaces(text: str) -> str:
    # Keep newlines intact; only collapse repeated spaces/tabs.
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def normalize_citation_label(label: str) -> str:
    cleaned = (
        label.replace("[", " ")
        .replace("]", " ")
        .replace("【", " ")
        .replace("】", " ")
    )
    return " ".join(cleaned.split()).strip()


def is_stable_citation_id(label: str) -> bool:
    return bool(_STABLE_CITATION_ID_RE.fullmatch((label or "").strip()))


def resolve_kb_refusal_answer(*, reason: str | None = None) -> str:
    reason_key = (reason or "").strip().lower()
    if reason_key == "clarify":
        return "为了更准确地回答，请补充关键约束信息后再继续。"
    if reason_key in {
        "exit_unanswerable",
        "no_evidence",
        "insufficient",
        "low_overlap",
    }:
        return "根据现有资料无法回答该问题。"
    if reason_key == "fallback_closed":
        return "根据现有资料无法回答该问题（未通过证据校验）。"
    return _RETRY_EXHAUSTED_NO_ANSWER


def is_kb_refusal_answer(answer: str) -> bool:
    text = _collapse_spaces((answer or "").strip())
    return any(text.startswith(prefix) for prefix in _NO_ANSWER_PREFIXES)


def _iter_citation_parts(raw_block: str) -> list[str]:
    parts = [p for p in _CITATION_SPLIT_RE.split(raw_block) if p and p.strip()]
    return parts or [raw_block]


def extract_citation_labels(text: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for match in _CITATION_BLOCK_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2) or ""
        for part in _iter_citation_parts(raw):
            label = normalize_citation_label(part)
            if not label:
                continue
            key = label.casefold()
            if key in seen:
                continue
            seen.add(key)
            labels.append(label)
    return labels


def enforce_kb_answer_citation_guardrails(
    answer: str,
    *,
    allowed_labels: list[str] | tuple[str, ...] | set[str] | None = None,
    allow_no_evidence: bool = False,
) -> str:
    """Enforce production guardrails for KB answers.

    - When evidence is required but missing: fail closed (no speculative answer).
    - When evidence exists: remove out-of-scope citations, and ensure at least one valid citation.
    - When evidence isn't required (e.g., clarify question): strip citation-like markers only.
    """

    text = (answer or "").strip()

    if allow_no_evidence or is_kb_refusal_answer(text):
        # Clarify questions may happen before retrieval. Still avoid citation-like markers.
        return _collapse_spaces(_CITATION_BLOCK_RE.sub("", text)) or text

    canonical_labels: dict[str, str] = {}
    for raw in allowed_labels or []:
        if not isinstance(raw, str):
            continue
        label = normalize_citation_label(raw)
        if not label:
            continue
        canonical_labels.setdefault(label.casefold(), label)

    if not canonical_labels:
        # Hard constraint: do not answer without evidence.
        return "根据现有资料无法回答该问题（未检索到相关证据）。"

    valid_found = False

    def _keep_valid(m: re.Match[str]) -> str:
        nonlocal valid_found
        raw = m.group(1) or m.group(2) or ""
        kept: list[str] = []
        for part in _iter_citation_parts(raw):
            label = normalize_citation_label(part)
            if not label:
                continue
            key = label.casefold()
            if key in canonical_labels:
                valid_found = True
                kept.append(f"[{canonical_labels[key]}]")
        return "".join(kept)

    cleaned = _collapse_spaces(_CITATION_BLOCK_RE.sub(_keep_valid, text))
    if not valid_found:
        first_label = next(iter(canonical_labels.values()))
        return f"{cleaned} [{first_label}]" if cleaned else f"[{first_label}]"
    return cleaned
