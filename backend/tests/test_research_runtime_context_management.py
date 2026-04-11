from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import app.services.deep_research_runtime as runtime_module
from app.schemas.research import ResearchPlanSnapshot
from app.services.deep_research_runtime import DeepResearchRuntime
from app.services.research_runtime_context import (
    build_runtime_context_guide,
    build_runtime_context_snapshot,
)
from app.services.research_workspace_files import build_research_workspace_layout


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot.model_validate(
        {
            "research_brief": "验证 runtime context 管理链路。",
            "complexity": "simple",
            "summary": "先接持久状态，再压缩上下文表面。",
            "subtasks": [
                {
                    "title": "收敛 runtime context",
                    "description": "让 runtime 只保留高信号上下文。",
                    "target_sources": ["web"],
                }
            ],
            "target_sources": ["web"],
        }
    )


def test_build_runtime_runner_uses_application_persistence_and_memory_paths(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel_checkpointer = object()
    sentinel_store = object()

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda **_: object())
    monkeypatch.setattr(
        runtime_module,
        "_resolve_recovery_structured_output_method",
        lambda settings=None: "function_calling",
    )
    monkeypatch.setattr(
        runtime_module,
        "get_prompt_loader",
        lambda: SimpleNamespace(render_with_few_shot=lambda *_args, **_kwargs: "runtime"),
    )
    monkeypatch.setattr(
        runtime_module.CheckpointManager,
        "initialize",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        runtime_module.StoreManager,
        "initialize",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        runtime_module.CheckpointManager,
        "get_checkpointer",
        lambda: sentinel_checkpointer,
    )
    monkeypatch.setattr(
        runtime_module.StoreManager,
        "get_store",
        lambda: sentinel_store,
    )

    async def _fake_create_deep_research_runtime(**kwargs: object) -> DeepResearchRuntime:
        captured.update(kwargs)
        return DeepResearchRuntime(
            agent=object(),
            config=kwargs["config"],
            tools=[],
            tool_meta_by_name={},
            tool_groups={},
        )

    monkeypatch.setattr(
        runtime_module, "create_deep_research_runtime", _fake_create_deep_research_runtime
    )

    asyncio.run(
        runtime_module.build_deep_research_runtime_runner(
            settings=SimpleNamespace(), http_client=None, redis=None
        )
    )

    assert captured["checkpointer"] is sentinel_checkpointer
    assert captured["store"] is sentinel_store
    assert captured["config"].memory_paths == (
        runtime_module.DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH,
    )


def test_build_runtime_memory_files_include_hygiene_metadata() -> None:
    memory_files = runtime_module._build_runtime_memory_files(
        session=SimpleNamespace(
            id="session-1",
            thread_id="thread-1",
            trace_id="research:session-1",
            question="如何优化 deep research 上下文管理？",
        ),
        plan_snapshot=_build_plan_snapshot(),
    )

    content = memory_files[runtime_module.DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH]

    assert "owner: deep_research_runtime" in content
    assert "scope: project" in content
    assert "confidence: high" in content
    assert "last_verified_at:" in content
    assert "live-board.json" in content


def test_runtime_context_snapshot_ignores_agent_authored_live_board_projection() -> None:
    layout = build_research_workspace_layout("session-1")

    snapshot = build_runtime_context_snapshot(
        result={
            "files": {
                layout.task_graph_path: {
                    "content": json.dumps(
                        {
                            "tasks": [
                                {
                                    "task_id": "claim-1",
                                    "title": "收口主张",
                                    "task_kind": "claim",
                                    "status": "pending",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
                layout.live_board_path: {
                    "content": json.dumps(
                        {
                            "current_task_label": "agent-authored",
                            "recent_activity": [{"task_id": "claim-1"}],
                        },
                        ensure_ascii=False,
                    )
                },
            }
        },
        layout=layout,
    )

    assert snapshot is not None
    assert snapshot.live_board_json == {}
    assert layout.live_board_path not in snapshot.files_snapshot


def test_runtime_context_guide_limits_first_pass_context_and_marks_layers() -> None:
    layout = build_research_workspace_layout("session-1")
    workspace_files = {
        layout.mission_path: "# mission\n",
        layout.plan_path: "# plan\n",
        layout.query_map_path: "# query-map\n",
        layout.coverage_path: "# coverage\n",
        layout.task_graph_path: "{}",
        layout.claim_bundles_path: "[]",
        layout.section_briefs_path: "[]",
        layout.report_context_json_path: "{}",
        layout.claim_map_md_path: "# claim-map\n",
        layout.evidence_ledger_md_path: "# evidence-ledger\n",
        layout.analysis_notes_path: "# analysis\n",
        layout.report_outline_path: "# outline\n",
        layout.report_draft_path: "# draft\n",
        layout.live_board_path: "{}",
        runtime_module.DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH: "# memory\n",
    }

    guide = build_runtime_context_guide(
        workspace_files=workspace_files,
        layout=layout,
    )

    assert layout.task_graph_path in guide.priority_paths
    assert layout.claim_bundles_path in guide.priority_paths
    assert layout.section_briefs_path in guide.priority_paths
    assert layout.report_context_json_path in guide.priority_paths
    assert layout.live_board_path not in guide.priority_paths
    assert layout.report_draft_path not in guide.priority_paths
    assert "## Projection Files" in guide.content
    assert f"- {layout.live_board_path}" in guide.content
    assert "## Persistent Memory" in guide.content
    assert runtime_module.DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH in guide.content
