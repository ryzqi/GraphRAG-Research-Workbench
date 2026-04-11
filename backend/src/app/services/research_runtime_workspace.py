from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from deepagents.backends.protocol import FileData
from deepagents.backends.utils import create_file_data

from app.models.research_session import ResearchSession
from app.prompts import get_prompt_loader
from app.schemas.research import ResearchPlanSnapshot
from app.services.research_query_mesh import build_research_query_mesh
from app.services.research_runtime_factory import resolve_source_subagent_route
from app.services.research_runtime_spill import spill_json_payload
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_workspace_bootstrap_artifact_path_map,
)

DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH = "/memories/deep-research/runtime-memory.md"

def _to_file_uri(path: str) -> str:
    normalized = "/" + path.lstrip("/")
    return f"file://{normalized}"


def _format_workspace_paths_block(workspace_paths: Sequence[str]) -> str:
    return "\n".join(f"- {path}" for path in workspace_paths)


def build_runtime_prompt(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    workspace_paths: Sequence[str],
) -> str:
    prompt_loader = get_prompt_loader()
    route_hint = ", ".join(resolve_source_subagent_route(plan_snapshot.target_sources))
    return prompt_loader.render_with_few_shot(
        "research/runtime_user",
        question=session.question,
        research_brief=plan_snapshot.research_brief,
        target_sources=", ".join(item.value for item in plan_snapshot.target_sources),
        route_hint=route_hint,
        workspace_paths_block=_format_workspace_paths_block(workspace_paths),
    )


def build_runtime_request_files(
    *,
    workspace_files: dict[str, str],
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, FileData]:
    query_mesh = build_research_query_mesh(
        question=session.question,
        plan_snapshot=plan_snapshot,
    )
    request_files: dict[str, FileData] = {
        path: create_file_data(content) for path, content in workspace_files.items()
    }
    request_files["/workspace/context/session_question.txt"] = create_file_data(
        session.question
    )
    request_files["/workspace/context/plan_snapshot.json"] = create_file_data(
        json.dumps(plan_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    request_files["/workspace/context/query_mesh.json"] = create_file_data(
        json.dumps(asdict(query_mesh), ensure_ascii=False, indent=2)
    )
    return request_files


def build_runtime_memory_files(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, str]:
    target_sources = ", ".join(item.value for item in plan_snapshot.target_sources) or "web"
    subtasks = [
        f"- {item.title}: {item.description}" for item in plan_snapshot.subtasks[:3]
    ] or ["- 当前未提供 planner subtasks。"]
    content = "\n".join(
        [
            "---",
            "owner: deep_research_runtime",
            "scope: project",
            "confidence: high",
            f"last_verified_at: {datetime.now(timezone.utc).isoformat()}",
            "update_policy: keep_only_verified_low_churn_rules",
            "---",
            "",
            "# Deep Research Runtime Memory",
            "",
            "## Stable Context Rules",
            "- `task-graph.json`, `claim-bundles.json`, `section-briefs.json`, and `report-context.json` are the primary runtime handoff surface.",
            "- `live-board.json` is a projection for runtime observability, not the single source of truth for planning state.",
            "- Persist only verified, low-churn runtime rules here. Do not store raw search results or transient tool dumps.",
            "",
            "## Current Runtime Contract",
            f"- session_id: `{session.id}`",
            f"- thread_id: `{session.thread_id}`",
            f"- trace_id: `{str(getattr(session, 'trace_id', '') or '')}`",
            f"- target_sources: `{target_sources}`",
            f"- research_brief: {plan_snapshot.research_brief}",
            "",
            "## Active Plan Summary",
            f"- planner_summary: {plan_snapshot.summary}",
            *subtasks,
            "",
        ]
    )
    return {DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH: content}


def _artifact_spill_slug_for_workspace_path(workspace_path: str) -> str:
    filename = PurePosixPath(workspace_path).name
    if filename.endswith(".md"):
        return filename[:-3]
    return filename


def _require_preloaded_session_artifacts(session: ResearchSession) -> Sequence[Any]:
    if "artifacts" not in session.__dict__:
        raise RuntimeError(
            "Deep Research runtime requires session.artifacts to be preloaded."
        )
    return session.artifacts or ()


def _build_bootstrap_workspace_file_entries(
    *,
    artifacts: Sequence[Any],
    layout: Any,
    path_by_artifact_key: dict[str, str],
    large_result_policy: Any,
) -> list[tuple[str, str]]:
    workspace_entries: list[tuple[str, str]] = []
    for artifact in artifacts:
        artifact_key = getattr(artifact, "artifact_key", None)
        if not isinstance(artifact_key, str):
            continue
        workspace_path = path_by_artifact_key.get(artifact_key)
        if workspace_path is None:
            continue
        content_text = getattr(artifact, "content_text", None)
        if not isinstance(content_text, str):
            continue
        if len(content_text) <= large_result_policy.max_inline_chars:
            workspace_entries.append((workspace_path, content_text))
            continue

        spill_prefix = (
            f"{large_result_policy.spill_path_prefix.rstrip('/')}/{layout.session_slug}"
        )
        spill_result = spill_json_payload(
            layout=layout,
            provider="workspace-bootstrap",
            slug=_artifact_spill_slug_for_workspace_path(workspace_path),
            payload={
                "artifact_key": artifact_key,
                "workspace_path": workspace_path,
                "content_text": content_text,
            },
            summary_lines=[
                f"- spilled artifact: {artifact_key}",
                f"- workspace path: {workspace_path}",
                f"- original size chars: {len(content_text)}",
            ],
            path_prefix=spill_prefix,
        )
        workspace_entries.extend(
            [
                (
                    workspace_path,
                    "\n".join(
                        [
                            "# Bootstrap Artifact Spill",
                            "",
                            f"- artifact_key: `{artifact_key}`",
                            f"- original_workspace_path: `{workspace_path}`",
                            f"- spill_summary_path: `{spill_result.summary_path}`",
                            f"- spill_raw_path: `{spill_result.raw_path}`",
                            f"- original_size_chars: {len(content_text)}",
                            "",
                            "请优先继续读取上述 spill 文件。",
                        ]
                    )
                    + "\n",
                ),
                (spill_result.summary_path, spill_result.summary_content),
                (spill_result.raw_path, spill_result.raw_content),
            ]
        )
    return workspace_entries


def build_session_bootstrap_workspace_files(
    *,
    session: ResearchSession,
    large_result_policy: Any,
) -> dict[str, str]:
    artifacts = _require_preloaded_session_artifacts(session)
    if not artifacts:
        return {}

    layout = build_research_workspace_layout(session.id)
    path_by_artifact_key = build_workspace_bootstrap_artifact_path_map(layout=layout)
    return dict(
        _build_bootstrap_workspace_file_entries(
            artifacts=artifacts,
            layout=layout,
            path_by_artifact_key=path_by_artifact_key,
            large_result_policy=large_result_policy,
        )
    )
