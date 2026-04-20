from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.settings import Settings
from app.services import deep_research_runtime
from app.services.research_runtime_types import ResearchLargeResultPolicy
from app.services.research_runtime_workspace import _build_bootstrap_workspace_file_entries
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_workspace_bootstrap_artifact_path_map,
)


def test_research_large_result_policy_defaults_are_budgeted() -> None:
    fields = Settings.model_fields

    assert fields["deep_research_large_result_max_inline_chars"].default == 2_000
    assert fields["deep_research_priority_inline_chars"].default == 12_000

    policy = ResearchLargeResultPolicy.from_settings(
        Settings(
            DEEP_RESEARCH_LARGE_RESULT_MAX_INLINE_CHARS=1_500,
            DEEP_RESEARCH_PRIORITY_INLINE_CHARS=9_000,
        )
    )

    assert policy.max_inline_chars == 1_500
    assert policy.priority_inline_chars == 9_000


def test_research_large_result_policy_rejects_priority_limit_below_default_limit() -> None:
    with pytest.raises(ValueError, match="priority_inline_chars"):
        ResearchLargeResultPolicy(max_inline_chars=4_000, priority_inline_chars=2_000)


def test_bootstrap_artifacts_use_priority_inline_limit_before_spilling() -> None:
    layout = build_research_workspace_layout("session-1")
    path_by_artifact_key = build_workspace_bootstrap_artifact_path_map(layout=layout)
    priority_content = "p" * 10
    non_priority_content = "n" * 10

    entries = dict(
        _build_bootstrap_workspace_file_entries(
            artifacts=[
                SimpleNamespace(
                    artifact_key="mission_md",
                    content_text=priority_content,
                ),
                SimpleNamespace(
                    artifact_key="report_draft_md",
                    content_text=non_priority_content,
                ),
            ],
            layout=layout,
            path_by_artifact_key=path_by_artifact_key,
            large_result_policy=ResearchLargeResultPolicy(
                max_inline_chars=5,
                priority_inline_chars=20,
            ),
        )
    )

    assert entries[layout.mission_path] == priority_content
    assert "Bootstrap Artifact Spill" in entries[layout.report_draft_path]
    assert any(
        path.startswith("/scratch/research-spill/session-1/")
        and non_priority_content in content
        for path, content in entries.items()
    )


@pytest.mark.asyncio
async def test_deep_research_runtime_runner_injects_large_result_policy_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def noop_async(*_args: object, **_kwargs: object) -> None:
        return None

    class FakePromptLoader:
        def render(self, *_args: object, **_kwargs: object) -> str:
            return "system"

    async def fake_create_deep_research_runtime(**kwargs: object) -> SimpleNamespace:
        captured["config"] = kwargs["config"]
        return SimpleNamespace(config=kwargs["config"])

    monkeypatch.setattr(
        deep_research_runtime.LangGraphPostgresPool,
        "initialize",
        noop_async,
    )
    monkeypatch.setattr(
        deep_research_runtime.CheckpointManager,
        "initialize",
        noop_async,
    )
    monkeypatch.setattr(
        deep_research_runtime.StoreManager,
        "initialize",
        noop_async,
    )
    monkeypatch.setattr(
        deep_research_runtime.CheckpointManager,
        "get_checkpointer",
        lambda: None,
    )
    monkeypatch.setattr(
        deep_research_runtime.StoreManager,
        "get_store",
        lambda: None,
    )
    monkeypatch.setattr(
        deep_research_runtime,
        "get_prompt_loader",
        lambda: FakePromptLoader(),
    )
    monkeypatch.setattr(
        deep_research_runtime,
        "create_chat_model",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        deep_research_runtime,
        "_resolve_recovery_structured_output_method",
        lambda settings: "function_calling",
    )
    monkeypatch.setattr(
        deep_research_runtime,
        "_build_workspace_context_files",
        lambda: {},
    )
    monkeypatch.setattr(
        deep_research_runtime,
        "create_deep_research_runtime",
        fake_create_deep_research_runtime,
    )

    await deep_research_runtime.build_deep_research_runtime_runner(
        settings=Settings(
            DEEP_RESEARCH_LARGE_RESULT_MAX_INLINE_CHARS=1_750,
            DEEP_RESEARCH_PRIORITY_INLINE_CHARS=8_500,
        ),
    )

    config = captured["config"]

    assert config.large_result_policy.max_inline_chars == 1_750
    assert config.large_result_policy.priority_inline_chars == 8_500
