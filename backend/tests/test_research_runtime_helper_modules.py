from __future__ import annotations

from types import SimpleNamespace

from app.schemas.research import ResearchPlanSnapshot
from app.services import research_runtime_recovery as recovery_module
from app.services import research_runtime_workspace as workspace_module


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot.model_validate(
        {
            "research_brief": "验证 runtime helper 模块拆分。",
            "complexity": "simple",
            "summary": "拆出 workspace 与 recovery helper。",
            "subtasks": [
                {
                    "title": "拆分 helper",
                    "description": "保持 runtime 入口语义不变。",
                    "target_sources": ["web"],
                }
            ],
            "target_sources": ["web"],
        }
    )


def test_workspace_module_builds_runtime_memory_files() -> None:
    memory_files = workspace_module.build_runtime_memory_files(
        session=SimpleNamespace(
            id="session-2",
            thread_id="thread-2",
            trace_id="research:session-2",
            question="如何拆分 deep research runtime helper？",
        ),
        plan_snapshot=_build_plan_snapshot(),
    )

    content = memory_files[workspace_module.DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH]

    assert "owner: deep_research_runtime" in content
    assert "scope: project" in content
    assert "confidence: high" in content


def test_recovery_module_uses_default_method_when_runtime_snapshot_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        recovery_module.ModelRuntimeConfigManager,
        "get_snapshot",
        lambda settings=None: (_ for _ in ()).throw(RuntimeError("missing snapshot")),
    )

    assert (
        recovery_module.resolve_recovery_structured_output_method(
            settings=SimpleNamespace()
        )
        == "function_calling"
    )