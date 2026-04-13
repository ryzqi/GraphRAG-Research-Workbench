from __future__ import annotations

from pathlib import Path

from app.config.provider_registry import (
    get_provider_descriptor,
    ordered_provider_descriptors,
)
from app.models.model_config import ModelProvider

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_provider_registry_local_providers_do_not_ship_loopback_defaults() -> None:
    ollama = get_provider_descriptor(ModelProvider.OLLAMA)
    llama_cpp = get_provider_descriptor(ModelProvider.LLAMA_CPP)

    for descriptor in (ollama, llama_cpp):
        assert "127.0.0.1" not in descriptor.base_url_placeholder
        assert "localhost" not in descriptor.base_url_placeholder
        assert descriptor.default_base_url is None

    ordered = ordered_provider_descriptors()
    assert [item.provider for item in ordered] == [
        ModelProvider.OPENAI,
        ModelProvider.OLLAMA,
        ModelProvider.LLAMA_CPP,
        ModelProvider.NVIDIA,
        ModelProvider.ANTHROPIC,
    ]


def test_repo_only_keeps_provider_tables_behind_registry_helpers() -> None:
    expectations = {
        REPO_ROOT / "backend/src/app/services/model_config_service.py": (
            "provider_order()",
            "_PROVIDER_ORDER = [",
        ),
        REPO_ROOT / "backend/src/app/integrations/model_runtime_config.py": (
            "provider_order()",
            "_PROVIDER_PRIORITY: tuple[ModelProvider, ...] = (",
        ),
        REPO_ROOT / "frontend/src/views/ModelConfigPage.tsx": (
            "useRuntimeConfig",
            "const PROVIDERS = [",
        ),
    }

    for path, (required_snippet, forbidden_snippet) in expectations.items():
        source = path.read_text(encoding="utf-8")
        assert required_snippet in source
        assert forbidden_snippet not in source
