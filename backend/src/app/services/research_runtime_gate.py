"""Deep Research runtime outline gate middleware."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from deepagents.backends import StateBackend
from langchain.agents.middleware import wrap_tool_call
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from app.services.research_workspace_files import build_research_workspace_layout

DEFAULT_OUTLINE_GATED_TOOL_NAMES = frozenset(
    {"web_search", "arxiv_search", "arxiv_fetch", "task"}
)
_PLACEHOLDER_SECTION_PREFIX = "<待补"
_READY_OUTLINE_STATUSES = {"ready", "completed", "complete", "done", "drafted"}
_SECTION_ID_HEADING_PATTERN = re.compile(
    r"^\[(?P<section_id>[^\[\]]+)\]\s*(?P<title>.*)$"
)


def tool_requires_outline_gate(
    tool_name: str, gated_tool_names: Collection[str] | None = None
) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    allowed = (
        frozenset(str(item).strip() for item in gated_tool_names if str(item).strip())
        if gated_tool_names is not None
        else DEFAULT_OUTLINE_GATED_TOOL_NAMES
    )
    return name in allowed


def evaluate_outline_gate_status(
    *,
    report_outline_md: str,
    report_context_json: Mapping[str, Any],
    section_briefs_json: Sequence[Mapping[str, Any]],
) -> tuple[bool, str | None]:
    outline_ready = bool(report_context_json.get("outline_ready"))
    outline_status = str(report_context_json.get("outline_status") or "").strip().lower()
    outline_sections = _parse_markdown_h2_sections(report_outline_md)
    real_outline_sections = [
        section
        for section in outline_sections
        if section["title"] and not section["title"].startswith(_PLACEHOLDER_SECTION_PREFIX)
    ]
    has_placeholder_sections = any(
        section["title"].startswith(_PLACEHOLDER_SECTION_PREFIX)
        for section in outline_sections
        if section["title"]
    )
    expected_briefs = [
        item
        for item in section_briefs_json
        if isinstance(item, Mapping)
        and (
            str(item.get("section_id") or "").strip()
            or str(item.get("title") or "").strip()
        )
    ]
    expected_section_ids = {
        str(item.get("section_id") or "").strip()
        for item in expected_briefs
        if str(item.get("section_id") or "").strip()
    }
    outline_section_ids = {
        str(section["section_id"]).strip()
        for section in outline_sections
        if str(section.get("section_id") or "").strip()
    }
    completed_brief_count = sum(
        1
        for item in expected_briefs
        if str(item.get("summary") or "").strip()
        or str(item.get("brief_markdown") or "").strip()
    )
    if (
        outline_ready
        and outline_status in _READY_OUTLINE_STATUSES
        and bool(expected_briefs)
        and not has_placeholder_sections
        and len(real_outline_sections) == len(expected_briefs)
        and completed_brief_count == len(expected_briefs)
        and (not outline_section_ids or outline_section_ids == expected_section_ids)
    ):
        return True, None
    return (
        False,
        "outline gate 未通过：请先写好完整 `report-outline`、为全部 section briefs 补齐简短说明，并把 `report-context` 的 `outline_ready/outline_status` 更新为完成状态。",
    )


def build_outline_gate_middleware(
    *, gated_tool_names: Collection[str] | None = None
) -> AgentMiddleware:
    resolved_tool_names = frozenset(
        str(item).strip()
        for item in (gated_tool_names or DEFAULT_OUTLINE_GATED_TOOL_NAMES)
        if str(item).strip()
    ) or DEFAULT_OUTLINE_GATED_TOOL_NAMES

    @wrap_tool_call
    def enforce_outline_gate(request, handler):
        tool_name = str(request.tool_call.get("name") or "").strip()
        if not tool_requires_outline_gate(tool_name, resolved_tool_names):
            return handler(request)

        report_outline_md, report_context_json, section_briefs_json = (
            _load_outline_gate_payloads(request.runtime.context)
        )
        allowed, reason = evaluate_outline_gate_status(
            report_outline_md=report_outline_md,
            report_context_json=report_context_json,
            section_briefs_json=section_briefs_json,
        )
        if allowed:
            return handler(request)

        return ToolMessage(
            content=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "OUTLINE_GATE_NOT_READY",
                        "message": reason,
                    },
                },
                ensure_ascii=False,
            ),
            name=tool_name or None,
            tool_call_id=str(request.tool_call.get("id") or ""),
            status="error",
        )

    return enforce_outline_gate


def _load_outline_gate_payloads(
    runtime_context: Any,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    session_id = str(getattr(runtime_context, "session_id", "") or "").strip()
    if not session_id:
        return "", {}, []

    layout = build_research_workspace_layout(session_id)
    backend = StateBackend()
    report_outline_md = _read_text_file(backend, layout.report_outline_path)
    report_context_json = _read_json_object(backend, layout.report_context_json_path)
    section_briefs_json = _read_json_array(backend, layout.section_briefs_path)
    return report_outline_md, report_context_json, section_briefs_json


def _read_text_file(backend: StateBackend, file_path: str) -> str:
    result = backend.read(file_path)
    if result.error or result.file_data is None:
        return ""
    content = result.file_data.get("content")
    encoding = str(result.file_data.get("encoding") or "utf-8")
    if encoding != "utf-8" or not isinstance(content, str):
        return ""
    return content


def _read_json_object(backend: StateBackend, file_path: str) -> dict[str, Any]:
    payload = _read_json_value(backend, file_path)
    return payload if isinstance(payload, dict) else {}


def _read_json_array(backend: StateBackend, file_path: str) -> list[dict[str, Any]]:
    payload = _read_json_value(backend, file_path)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _read_json_value(backend: StateBackend, file_path: str) -> Any:
    content = _read_text_file(backend, file_path).strip()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _parse_markdown_h2_sections(value: str) -> list[dict[str, str]]:
    if not value.strip():
        return []
    sections: list[dict[str, str]] = []
    current_title = ""
    current_section_id = ""
    current_lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_title:
                sections.append(
                    {
                        "section_id": current_section_id,
                        "title": current_title,
                        "content": "\n".join(current_lines).strip(),
                    }
                )
            current_section_id, current_title = _split_section_heading(stripped[3:].strip())
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append(
            {
                "section_id": current_section_id,
                "title": current_title,
                "content": "\n".join(current_lines).strip(),
            }
        )
    return sections


def _split_section_heading(raw_heading: str) -> tuple[str, str]:
    heading = raw_heading.strip()
    if not heading:
        return "", ""
    match = _SECTION_ID_HEADING_PATTERN.match(heading)
    if match is None:
        return "", heading
    return (
        str(match.group("section_id") or "").strip(),
        str(match.group("title") or "").strip(),
    )
