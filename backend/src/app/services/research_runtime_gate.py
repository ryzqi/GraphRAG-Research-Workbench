"""Deep Research runtime breadth gate middleware。

在 claim-map.json / evidence-ledger.json 的 breadth 条件未达标前，
阻止 section-writer / citation-steward 委派，
但不阻止 web_search / arxiv_search 的证据搜集。
"""

from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any

from deepagents.backends import StateBackend
from langchain.agents.middleware import wrap_tool_call
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from app.schemas.research_workspace import (
    ResearchClaimMap,
    ResearchEvidenceLedger,
)
from app.services.research_workspace_files import build_research_workspace_layout

DEFAULT_BREADTH_GATED_TOOL_NAMES = frozenset({"task"})

_MIN_EVIDENCE_PER_CLAIM_BY_COMPLEXITY: dict[str, int] = {
    "simple": 1,
    "comparative": 2,
    "complex": 2,
}
_GATED_SUBAGENTS = {"section-writer", "citation-steward"}
_EMPTY_GENERATED_AT = "1970-01-01T00:00:00Z"


def tool_requires_breadth_gate(
    tool_name: str, gated_tool_names: Collection[str] | None = None
) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    allowed = (
        frozenset(str(item).strip() for item in gated_tool_names if str(item).strip())
        if gated_tool_names is not None
        else DEFAULT_BREADTH_GATED_TOOL_NAMES
    )
    return name in allowed


def _evidence_counts_by_claim(
    ledger: ResearchEvidenceLedger,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for evidence in ledger.evidences:
        for claim_id in evidence.claim_ids:
            counts[claim_id] = counts.get(claim_id, 0) + 1
    return counts


def evaluate_breadth_gate_status(
    *,
    claim_map: ResearchClaimMap,
    evidence_ledger: ResearchEvidenceLedger,
    plan_complexity: str,
) -> tuple[bool, str | None]:
    min_required = _MIN_EVIDENCE_PER_CLAIM_BY_COMPLEXITY.get(plan_complexity, 1)
    evidence_counts = _evidence_counts_by_claim(evidence_ledger)
    pending_under_threshold = [
        claim
        for claim in claim_map.claims
        if claim.status == "pending"
        and evidence_counts.get(claim.claim_id, 0) < min_required
    ]
    if pending_under_threshold:
        names = ", ".join(claim.claim_id for claim in pending_under_threshold)
        return (
            False,
            f"breadth gate 未通过：pending claim {names} 的 evidence 数量低于 {min_required}，"
            "请先完成 breadth-pass 再尝试锁定 outline / 派发 section-writer。",
        )
    return True, None


def build_breadth_gate_middleware(
    *, gated_tool_names: Collection[str] | None = None
) -> AgentMiddleware:
    resolved_tool_names = frozenset(
        str(item).strip()
        for item in (gated_tool_names or DEFAULT_BREADTH_GATED_TOOL_NAMES)
        if str(item).strip()
    ) or DEFAULT_BREADTH_GATED_TOOL_NAMES

    @wrap_tool_call
    async def enforce_breadth_gate(request, handler):
        tool_name = str(request.tool_call.get("name") or "").strip()
        if not tool_requires_breadth_gate(tool_name, resolved_tool_names):
            return await handler(request)

        args = request.tool_call.get("args") or {}
        target = str(args.get("subagent_name") or args.get("name") or "").strip()
        if target not in _GATED_SUBAGENTS:
            return await handler(request)

        claim_map, ledger, complexity = _load_breadth_gate_inputs(
            request.runtime.context
        )
        allowed, reason = evaluate_breadth_gate_status(
            claim_map=claim_map,
            evidence_ledger=ledger,
            plan_complexity=complexity,
        )
        if allowed:
            return await handler(request)
        return ToolMessage(
            content=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "BREADTH_GATE_NOT_READY",
                        "message": reason,
                    },
                },
                ensure_ascii=False,
            ),
            name=tool_name or None,
            tool_call_id=str(request.tool_call.get("id") or ""),
            status="error",
        )

    return enforce_breadth_gate


def _load_breadth_gate_inputs(
    runtime_context: Any,
) -> tuple[ResearchClaimMap, ResearchEvidenceLedger, str]:
    session_id = str(getattr(runtime_context, "session_id", "") or "").strip()
    complexity = str(getattr(runtime_context, "plan_complexity", "") or "simple").strip()
    if not session_id:
        return _empty_claim_map(), _empty_evidence_ledger(), complexity

    layout = build_research_workspace_layout(session_id)
    backend = StateBackend()
    claim_map = _read_claim_map(backend, layout.claim_map_json_path)
    ledger = _read_evidence_ledger(backend, layout.evidence_ledger_json_path)
    return claim_map, ledger, complexity


def _read_claim_map(backend: StateBackend, path: str) -> ResearchClaimMap:
    text = _read_text(backend, path)
    if not text:
        return _empty_claim_map()
    try:
        return ResearchClaimMap.model_validate_json(text)
    except ValueError:
        return _empty_claim_map()


def _read_evidence_ledger(backend: StateBackend, path: str) -> ResearchEvidenceLedger:
    text = _read_text(backend, path)
    if not text:
        return _empty_evidence_ledger()
    try:
        return ResearchEvidenceLedger.model_validate_json(text)
    except ValueError:
        return _empty_evidence_ledger()


def _read_text(backend: StateBackend, path: str) -> str:
    result = backend.read(path)
    if result.error or result.file_data is None:
        return ""
    content = result.file_data.get("content")
    encoding = str(result.file_data.get("encoding") or "utf-8")
    if encoding != "utf-8" or not isinstance(content, str):
        return ""
    return content


def _empty_claim_map() -> ResearchClaimMap:
    return ResearchClaimMap.model_validate(
        {"claims": [], "generated_at": _EMPTY_GENERATED_AT}
    )


def _empty_evidence_ledger() -> ResearchEvidenceLedger:
    return ResearchEvidenceLedger.model_validate(
        {"evidences": [], "generated_at": _EMPTY_GENERATED_AT}
    )
