from __future__ import annotations

from types import SimpleNamespace

from deepagents.backends import StateBackend

from app.services.research_runtime_types import ResearchWorkspaceBudget
from app.services.research_runtime_workspace_backend import (
    WorkspaceSeedBackend,
    WorkspaceSeedRegistry,
)
from app.services.research_runtime_workspace import (
    build_runtime_request_files_with_budget,
)
from app.services import research_runtime_factory
from app.services.research_runtime_types import ResearchRuntimeConfig


def test_runtime_request_files_only_preload_priority_paths_when_on_demand_enabled() -> None:
    files = {
        "/workspace/context/session_question.txt": "question",
        "/workspace/context/plan_snapshot.json": '{"summary":"plan"}',
        "/workspace/research/demo/00-mission.md": "mission",
        "/workspace/research/demo/extra-notes.md": "extra notes that should stay on-demand",
    }

    request_files, snapshot = build_runtime_request_files_with_budget(
        files=files,
        priority_paths=(
            "/workspace/context/session_question.txt",
            "/workspace/context/plan_snapshot.json",
            "/workspace/research/demo/00-mission.md",
        ),
        budget=ResearchWorkspaceBudget(total_tokens_budget=60_000, priority_reserve=30_000),
        include_non_priority_files=False,
    )

    assert set(request_files) == {
        "/workspace/context/session_question.txt",
        "/workspace/context/plan_snapshot.json",
        "/workspace/research/demo/00-mission.md",
    }
    assert snapshot["spilled_paths"] == ["/workspace/research/demo/extra-notes.md"]
    assert snapshot["on_demand_only"] is True


def test_workspace_seed_backend_reads_seed_files_and_prefers_runtime_overrides() -> None:
    registry = WorkspaceSeedRegistry()
    registry.set(
        session_id="session-1",
        seed_files={
            "/workspace/research/demo/extra-notes.md": "seed content",
        },
    )
    backend = WorkspaceSeedBackend(
        runtime_backend=StateBackend(),
        registry=registry,
    )
    backend._seed_files = lambda: registry.get(session_id="session-1")  # type: ignore[method-assign]

    seeded = backend.read("/workspace/research/demo/extra-notes.md")

    assert seeded.error is None
    assert seeded.file_data is not None
    assert seeded.file_data["content"] == "seed content"

    listed = backend.ls("/workspace/research/demo")
    assert listed.error is None
    assert listed.entries is not None
    assert any(
        entry["path"] == "/workspace/research/demo/extra-notes.md"
        for entry in listed.entries
    )

    globbed = backend.glob("*.md", path="/workspace/research/demo")
    assert globbed.error is None
    assert globbed.matches is not None
    assert any(
        entry["path"] == "/workspace/research/demo/extra-notes.md"
        for entry in globbed.matches
    )

    grep_result = backend.grep("seed content", path="/workspace/research/demo")
    assert grep_result.error is None
    assert grep_result.matches is not None
    assert any(
        match["path"] == "/workspace/research/demo/extra-notes.md"
        for match in grep_result.matches
    )

    registry.clear(session_id="session-1")
    assert registry.get(session_id="session-1") == {}


def test_workspace_seed_backend_lists_seed_directories_for_skills_and_nested_workspace() -> None:
    registry = WorkspaceSeedRegistry()
    registry.set(
        session_id="session-1",
        seed_files={
            "/skills/research-runtime/SKILL.md": "---\nname: runtime\n---\n",
            "/skills/research-reporting/SKILL.md": "---\nname: reporting\n---\n",
            "/workspace/research/demo/critique/evidence-critique.json": '{"ok":true}',
            "/memories/deep-research/runtime-memory.md": "memory content",
        },
    )
    backend = WorkspaceSeedBackend(
        runtime_backend=StateBackend(),
        registry=registry,
    )
    backend._seed_files = lambda: registry.get(session_id="session-1")  # type: ignore[method-assign]

    skills_root = backend.ls("/skills/")

    assert skills_root.error is None
    assert skills_root.entries is not None
    assert any(
        entry["path"] == "/skills/research-runtime/" and entry["is_dir"] is True
        for entry in skills_root.entries
    )
    assert any(
        entry["path"] == "/skills/research-reporting/" and entry["is_dir"] is True
        for entry in skills_root.entries
    )

    workspace_root = backend.ls("/workspace/research/demo")

    assert workspace_root.error is None
    assert workspace_root.entries is not None
    assert any(
        entry["path"] == "/workspace/research/demo/critique/"
        and entry["is_dir"] is True
        for entry in workspace_root.entries
    )

    nested_dir = backend.ls("/workspace/research/demo/critique")

    assert nested_dir.error is None
    assert nested_dir.entries is not None
    assert any(
        entry["path"] == "/workspace/research/demo/critique/evidence-critique.json"
        and entry["is_dir"] is False
        for entry in nested_dir.entries
    )

    downloads = backend.download_files(
        [
            "/skills/research-runtime/SKILL.md",
            "/memories/deep-research/runtime-memory.md",
        ]
    )

    assert downloads[0].error is None
    assert downloads[0].content == b"---\nname: runtime\n---\n"
    assert downloads[1].error is None
    assert downloads[1].content == b"memory content"


def test_create_deep_research_runtime_keeps_workspace_seed_registry(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_build_research_tool_registry(**_kwargs):
        return SimpleNamespace(
            tools=[],
            tool_meta_by_name={},
            tool_groups={},
        )

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        research_runtime_factory,
        "build_research_tool_registry",
        fake_build_research_tool_registry,
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "create_deep_agent",
        fake_create_deep_agent,
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "_assemble_research_subagents",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "build_breadth_gate_middleware",
        lambda **_kwargs: "breadth",
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "build_agent_model_safety_middleware",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        research_runtime_factory,
        "build_tool_selector_middleware",
        lambda **_kwargs: [],
    )

    registry = WorkspaceSeedRegistry()
    config = ResearchRuntimeConfig(
        primary_model=SimpleNamespace(),
        subagent_model=SimpleNamespace(),
        system_prompt="system",
    )

    import asyncio

    runtime = asyncio.run(
        research_runtime_factory.create_deep_research_runtime(
            settings=SimpleNamespace(),
            config=config,
            workspace_seed_registry=registry,
        )
    )

    assert runtime.workspace_seed_registry is registry
    assert captured["backend"].default.registry is registry
