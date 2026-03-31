from __future__ import annotations

from app.services.research_runtime_spill import spill_json_payload
from app.services.research_runtime_types import ResearchRuntimeConfig
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_workspace_bootstrap_artifact_path_map,
)


def test_spill_json_payload_writes_summary_and_raw_files() -> None:
    layout = build_research_workspace_layout("session-1")

    result = spill_json_payload(
        layout=layout,
        provider="searxng",
        slug="breadth-query",
        payload={"results": [{"title": "A"}] * 20},
        summary_lines=["- breadth query captured 20 results"],
    )

    assert (
        result.summary_path
        == "/scratch/research/session-1/evidence/searxng/breadth-query.summary.md"
    )
    assert (
        result.raw_path
        == "/scratch/research/session-1/evidence/searxng/breadth-query.raw.json"
    )
    assert "20 results" in result.summary_content
    assert '"results"' in result.raw_content


def test_research_runtime_config_uses_scratch_spill_policy_defaults() -> None:
    config = ResearchRuntimeConfig(
        primary_model="gpt-5.2",
        subagent_model="gpt-5.2-mini",
        system_prompt="你是深度研究助手。",
    )

    assert config.large_result_policy.spill_path_prefix == "/scratch/research-spill/"
    assert config.large_result_policy.max_inline_chars == 6_000


def test_spill_json_payload_supports_policy_path_prefix_override() -> None:
    layout = build_research_workspace_layout("session-1")

    result = spill_json_payload(
        layout=layout,
        provider="workspace-bootstrap",
        slug="00-mission",
        payload={"artifact_key": "mission_md", "content_text": "# Mission"},
        summary_lines=["- spilled oversized mission artifact"],
        path_prefix="/scratch/research-spill/session-1",
    )

    assert (
        result.summary_path
        == "/scratch/research-spill/session-1/workspace-bootstrap/00-mission.summary.md"
    )
    assert (
        result.raw_path
        == "/scratch/research-spill/session-1/workspace-bootstrap/00-mission.raw.json"
    )


def test_workspace_bootstrap_artifact_path_map_uses_layout_as_single_source() -> None:
    layout = build_research_workspace_layout("session-1")

    path_map = build_workspace_bootstrap_artifact_path_map(layout=layout)

    assert path_map["mission_md"] == layout.mission_path
    assert path_map["plan_md"] == layout.plan_path
    assert path_map["query_map_md"] == layout.query_map_path
    assert path_map["coverage_md"] == layout.coverage_path
    assert path_map["report_draft_md"] == layout.report_draft_path
