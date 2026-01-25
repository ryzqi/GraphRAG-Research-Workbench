"""Evidence/citation guardrails for KB chat.

KB chat answers use bracketed numeric citations like "[1]" that correspond to the
ordered evidence snippets returned by `kb_retrieve`.
"""

from __future__ import annotations

import re

_CITATION_RE = re.compile(r"\[(\d+)\]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _collapse_spaces(text: str) -> str:
    # Keep newlines intact; only collapse repeated spaces/tabs.
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def enforce_kb_answer_citation_guardrails(
    answer: str,
    *,
    evidence_count: int,
    allow_no_evidence: bool = False,
) -> str:
    """Enforce production guardrails for KB answers.

    - When evidence is required but missing: fail closed (no speculative answer).
    - When evidence exists: remove out-of-range citations, and ensure at least one valid citation.
    - When evidence isn't required (e.g., clarify question): strip citation-like markers only.
    """

    text = (answer or "").strip()

    if allow_no_evidence:
        # Clarify questions may happen before retrieval. Still avoid citation-like markers.
        return _collapse_spaces(_CITATION_RE.sub("", text)) or text

    if evidence_count <= 0:
        # Hard constraint: do not answer without evidence.
        return "根据现有资料无法回答该问题（未检索到相关证据）。"

    valid_found = False

    def _keep_valid(m: re.Match[str]) -> str:
        nonlocal valid_found
        try:
            idx = int(m.group(1))
        except Exception:
            return ""
        if 1 <= idx <= evidence_count:
            valid_found = True
            return m.group(0)
        return ""

    cleaned = _collapse_spaces(_CITATION_RE.sub(_keep_valid, text))
    if not valid_found:
        return f"{cleaned} [1]" if cleaned else "[1]"
    return cleaned

