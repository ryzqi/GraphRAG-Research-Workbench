"""Deep Research runtime 大结果溢写辅助。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.services.research_workspace_files import ResearchWorkspaceLayout


@dataclass(slots=True, frozen=True)
class SpillResult:
    summary_path: str
    raw_path: str
    summary_content: str
    raw_content: str


def spill_json_payload(
    *,
    layout: ResearchWorkspaceLayout,
    provider: str,
    slug: str,
    payload: dict[str, Any] | list[Any],
    summary_lines: list[str],
    path_prefix: str | None = None,
) -> SpillResult:
    if path_prefix is None:
        base_dir = f"{layout.scratch_root}/evidence/{provider}"
    else:
        base_dir = f"{path_prefix.rstrip('/')}/{provider}"
    summary_path = f"{base_dir}/{slug}.summary.md"
    raw_path = f"{base_dir}/{slug}.raw.json"
    summary_content = "# Evidence Summary\n\n" + "\n".join(summary_lines) + "\n"
    raw_content = json.dumps(payload, ensure_ascii=False, indent=2)
    return SpillResult(
        summary_path=summary_path,
        raw_path=raw_path,
        summary_content=summary_content,
        raw_content=raw_content,
    )
