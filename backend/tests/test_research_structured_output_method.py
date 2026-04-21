from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.model_runtime_config import RuntimeModelSnapshot, RuntimeProviderConfig
from app.models.model_config import ModelProvider
from app.services.research_planner import LLMResearchScoper
from app.services.research_runtime_recovery import (
    resolve_recovery_structured_output_method,
)
from app.services.research_service import build_research_service


def _snapshot(provider: ModelProvider) -> RuntimeModelSnapshot:
    return RuntimeModelSnapshot(
        providers={
            provider: RuntimeProviderConfig(
                provider=provider,
                enabled=True,
                base_url="http://127.0.0.1:8080/v1",
                api_key=None,
                models=["test-model"],
                thinking_enabled=False,
                thinking_level=None,
            )
        },
        active_provider=provider,
        active_model="test-model",
        updated_at=datetime.now(timezone.utc),
    )


def test_llama_cpp_scoper_uses_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.research_planner.ModelRuntimeConfigManager.get_snapshot",
        lambda settings=None: _snapshot(ModelProvider.LLAMA_CPP),
    )

    scoper = LLMResearchScoper()

    assert scoper._structured_output_method() == "json_mode"


def test_llama_cpp_recovery_uses_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.research_runtime_recovery.ModelRuntimeConfigManager.get_snapshot",
        lambda settings=None: _snapshot(ModelProvider.LLAMA_CPP),
    )

    assert resolve_recovery_structured_output_method() == "json_mode"


def test_build_research_service_uses_json_mode_alignment_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.research_service.ModelRuntimeConfigManager.get_snapshot",
        lambda settings=None: _snapshot(ModelProvider.LLAMA_CPP),
    )
    monkeypatch.setattr(
        "app.services.research_service.create_chat_model_cached",
        lambda settings, use_previous_response_id: object(),
    )

    service = build_research_service(db=object())  # type: ignore[arg-type]

    assert service._finalizer._judge is not None
    assert service._finalizer._judge._structured_method == "json_mode"
