"""Deep Research runtime 文件化上下文管理。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config.runtime_contract import (
    RESEARCH_RUNTIME_BACKEND_ROOTS,
    RESEARCH_RUNTIME_LAYOUT_MANIFEST,
    RESEARCH_RUNTIME_REQUEST_CONTEXT,
)
from app.services.research_workspace_files import ResearchWorkspaceLayout


@dataclass(slots=True, frozen=True)
class ResearchRuntimeContextSnapshot:
    claim_map_md: str = ""
    evidence_ledger_md: str = ""
    analysis_notes_md: str = ""
    claim_map_json: dict[str, Any] = field(default_factory=dict)
    evidence_ledger_json: dict[str, Any] = field(default_factory=dict)
    report_outline_md: str = ""
    report_draft_md: str = ""
    report_context_json: dict[str, Any] = field(default_factory=dict)
    task_graph_json: dict[str, Any] = field(default_factory=dict)
    claim_bundles_json: list[dict[str, Any]] = field(default_factory=list)
    section_briefs_json: list[dict[str, Any]] = field(default_factory=list)
    live_board_json: dict[str, Any] = field(default_factory=dict)
    evidence_critique_json: dict[str, Any] = field(default_factory=dict)
    coverage_critique_json: dict[str, Any] = field(default_factory=dict)
    todos_json: list[dict[str, Any]] = field(default_factory=list)
    files_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ResearchRuntimeContextGuide:
    path: str
    content: str
    priority_paths: tuple[str, ...]


def _dedupe_paths(paths: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return tuple(ordered)


def _build_priority_context_paths(
    *,
    workspace_files: Mapping[str, str],
    layout: ResearchWorkspaceLayout,
) -> tuple[str, ...]:
    layout_priority_paths = tuple(
        getattr(layout, attr_name)
        for attr_name in RESEARCH_RUNTIME_LAYOUT_MANIFEST.priority_layout_attrs
    )
    return _dedupe_paths(
        (
            RESEARCH_RUNTIME_REQUEST_CONTEXT.guide_path,
            *RESEARCH_RUNTIME_REQUEST_CONTEXT.request_paths,
            *layout_priority_paths,
        )
    )


def build_runtime_context_guide(
    *,
    workspace_files: Mapping[str, str],
    layout: ResearchWorkspaceLayout,
) -> ResearchRuntimeContextGuide:
    priority_paths = _build_priority_context_paths(
        workspace_files=workspace_files,
        layout=layout,
    )
    skill_paths = sorted(
        path
        for path in workspace_files
        if path.startswith(RESEARCH_RUNTIME_BACKEND_ROOTS.skills_root)
    )
    memory_paths = sorted(
        path
        for path in workspace_files
        if path.startswith(RESEARCH_RUNTIME_BACKEND_ROOTS.memories_root)
    )
    scratch_paths = sorted(
        path
        for path in workspace_files
        if path.startswith(RESEARCH_RUNTIME_BACKEND_ROOTS.scratch_root)
    )
    projection_paths = [
        path
        for attr_name in RESEARCH_RUNTIME_LAYOUT_MANIFEST.projection_layout_attrs
        if (path := getattr(layout, attr_name)) in workspace_files
    ]
    on_demand_paths = [
        path
        for attr_name in RESEARCH_RUNTIME_LAYOUT_MANIFEST.analysis_layout_attrs
        if (path := getattr(layout, attr_name)) in workspace_files
        if path in workspace_files
    ]
    lines = [
        "# Runtime Context Guide",
        "",
        "## Priority Read Order",
        *[f"- {path}" for path in priority_paths],
        "",
        "## Layering Rules",
        "- First-pass context should stay limited to the priority read order above.",
        "- `claim-map.json`, `evidence-ledger.json`, `task-graph.json`, and `report-context.json` are the runtime handoff surface.",
        f"- `{layout.live_board_path}` is a projection for runtime observability, not the planning source of truth.",
        "- `/skills/*` are procedural instructions. Read them only when the task requires their behavior.",
        "- `/memories/*` files hold low-churn runtime rules and should stay concise.",
        "- `/scratch/*` files are spillover or raw payloads. Treat them as on-demand details, not first-pass context.",
        "",
        "## Runtime Output Targets",
        f"- Persist `report-context.json` to `{layout.report_context_json_path}`.",
    ]
    if projection_paths:
        lines.extend(
            [
                "",
                "## Projection Files",
                *[f"- {path}" for path in projection_paths],
            ]
        )
    if on_demand_paths:
        lines.extend(
            [
                "",
                "## On-Demand Analysis Files",
                *[f"- {path}" for path in on_demand_paths],
            ]
        )
    if skill_paths:
        lines.extend(
            [
                "",
                "## Procedural Skills",
                *[f"- {path}" for path in skill_paths],
            ]
        )
    if memory_paths:
        lines.extend(
            [
                "",
                "## Persistent Memory",
                *[f"- {path}" for path in memory_paths],
            ]
        )
    if scratch_paths:
        lines.extend(
            [
                "",
                "## Scratch Or Spill Files",
                *[f"- {path}" for path in scratch_paths],
            ]
        )
    return ResearchRuntimeContextGuide(
        path=RESEARCH_RUNTIME_REQUEST_CONTEXT.guide_path,
        content="\n".join(lines) + "\n",
        priority_paths=priority_paths,
    )


def _coerce_file_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""

    content = payload.get("content")
    if isinstance(content, str):
        return content

    value = payload.get("value")
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text

    text = payload.get("text")
    if isinstance(text, str):
        return text
    return ""


def _parse_report_context_payload(raw_text: str) -> dict[str, Any]:
    if not raw_text.strip():
        return {}
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_json_object_payload(raw_text: str) -> dict[str, Any]:
    if not raw_text.strip():
        return {}
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_json_array_payload(raw_text: str) -> list[dict[str, Any]]:
    if not raw_text.strip():
        return []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _parse_todos_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    todos: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        status = str(item.get("status") or "").strip()
        if not content:
            continue
        todo = dict(item)
        todo["content"] = content
        if status:
            todo["status"] = status
        todos.append(todo)
    return todos


def build_runtime_context_snapshot(
    *,
    result: dict[str, Any],
    layout: ResearchWorkspaceLayout,
    baseline_files: Mapping[str, str] | None = None,
) -> ResearchRuntimeContextSnapshot | None:
    files = result.get("files")
    if not isinstance(files, dict):
        return None
    baseline = baseline_files or {}
    todos = _parse_todos_payload(result.get("todos"))

    whitelist = {
        getattr(layout, attr_name)
        for attr_name in RESEARCH_RUNTIME_LAYOUT_MANIFEST.snapshot_layout_attrs
    }
    extracted: dict[str, str] = {}
    for path, payload in files.items():
        if path not in whitelist:
            continue
        text = _coerce_file_text(payload)
        if text:
            baseline_text = baseline.get(path)
            if isinstance(baseline_text, str) and text.strip() == baseline_text.strip():
                continue
            extracted[path] = text

    if not extracted and not todos:
        return None

    report_context_payload = extracted.get(layout.report_context_json_path, "")
    return ResearchRuntimeContextSnapshot(
        claim_map_json=_parse_json_object_payload(
            extracted.get(layout.claim_map_json_path, "")
        ),
        evidence_ledger_json=_parse_json_object_payload(
            extracted.get(layout.evidence_ledger_json_path, "")
        ),
        report_outline_md=extracted.get(layout.report_outline_path, ""),
        report_draft_md=extracted.get(layout.report_draft_path, ""),
        report_context_json=_parse_report_context_payload(report_context_payload),
        task_graph_json=_parse_json_object_payload(
            extracted.get(layout.task_graph_path, "")
        ),
        claim_bundles_json=_parse_json_array_payload(
            extracted.get(layout.claim_bundles_path, "")
        ),
        section_briefs_json=_parse_json_array_payload(
            extracted.get(layout.section_briefs_path, "")
        ),
        live_board_json=_parse_json_object_payload(
            extracted.get(layout.live_board_path, "")
        ),
        evidence_critique_json=_parse_json_object_payload(
            extracted.get(layout.evidence_critique_json_path, "")
        ),
        coverage_critique_json=_parse_json_object_payload(
            extracted.get(layout.coverage_critique_json_path, "")
        ),
        todos_json=todos,
        files_snapshot=extracted,
    )
