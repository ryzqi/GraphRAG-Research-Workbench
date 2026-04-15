"""KB Chat agentic reflection 共享辅助。"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from app.core.settings import Settings, get_settings

from .json_safety import ensure_json_safe

_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
StateView = Mapping[str, object]
_INLINE_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,128})\]|【([^【】\n]{1,128})】")
_CITATION_ONLY_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
}
_LATIN_TERM_RE = re.compile(r"[（(]([A-Za-z][A-Za-z0-9\-/ ]{1,64})[)）]")
_RESPONSIBILITY_LABEL_RE = re.compile(
    r"(?:核心任务|职责|作用)\s*[：:]\s*([^（(。\n；;，,]+)"
)
_RESPONSIBILITY_STAGE_RE = re.compile(
    r"负责([^，。,；;\n（(]{1,20})(?:[（(]([^()（）\n]{1,32})[)）])?"
)


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _as_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _get_loop_counts(state: StateView) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _current_retrieval_round(state: StateView) -> int:
    loop_counts = _get_loop_counts(state)
    return max(int(loop_counts.get("retrieval_retries") or 0), 0)


def _total_rounds_exceeded(loop_counts: dict[str, int], settings: Settings) -> bool:
    return loop_counts.get("total_rounds", 0) >= int(settings.kb_chat_max_total_rounds)


def _extract_evidence_count(final_context: str) -> int:
    if not final_context:
        return 0
    return sum(1 for _ in _EVIDENCE_LINE_RE.finditer(final_context))



def _merge_stage_summary(
    state: StateView, key: str, summary: dict[str, Any]
) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    settings = get_settings()
    safe_summary = ensure_json_safe(
        summary, settings=settings, label=f"stage_summaries.{key}"
    )
    merged = {**stage_summaries, key: safe_summary}
    merged = ensure_json_safe(merged, settings=settings, label="stage_summaries")
    return {"stage_summaries": merged}


def _merge_reflection(state: StateView, patch: dict[str, Any]) -> dict[str, Any]:
    reflection = state.get("reflection")
    if not isinstance(reflection, dict):
        reflection = {}
    return {"reflection": {**reflection, **patch}}


def _set_final_answer_for_exit(
    state: StateView, answer: str, *, reason: str
) -> dict[str, Any]:
    # ForceExit 节点优先使用 final_answer；这里显式设置，避免泄露历史 AIMessage。
    return {
        "final_answer": answer,
        **_merge_reflection(state, {"action": "force_exit", "reason": reason}),
    }


def _resolve_query_text(state: StateView) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("resolved_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


