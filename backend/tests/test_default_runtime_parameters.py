from app.config.deploy_settings import ENV_FILE
from app.config.policy_loader import load_frontend_runtime_policy
from app.core.settings import Settings
from app.schemas.chats import default_kb_chat_config
from app.schemas.knowledge_bases import IndexConfig
from app.services.research_observability import (
    ResearchGateThresholds,
    build_research_gate_thresholds,
)


def _read_env_assignment(key: str) -> str | None:
    if not ENV_FILE.exists():
        return None

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def test_kb_chat_default_config_uses_updated_retrieval_budget() -> None:
    assert Settings.model_fields["retrieval_max_top_k"].default == 40

    settings = Settings(
        _env_file=None,
        retrieval_default_top_k=12,
        retrieval_max_top_k=40,
        retrieval_hybrid_rrf_k=60,
    )

    config = default_kb_chat_config(settings=settings)

    assert config.retrieval_top_k == 12
    assert config.retrieval_rerank_top_k == 40
    assert config.retrieval_hybrid_rrf_k == 60


def test_frontend_runtime_and_index_defaults_match_updated_values() -> None:
    assert Settings.model_fields["frontend_export_poll_interval_ms"].default == 2000

    runtime_policy = load_frontend_runtime_policy()
    index_config = IndexConfig.model_validate({})

    assert runtime_policy.export_poll_interval_ms == 2000
    assert index_config.chunking.semantic.embedding_batch_size == 32


def test_research_gate_defaults_to_three_minute_p95_budget() -> None:
    assert ResearchGateThresholds().max_p95_ms == 180_000
    assert build_research_gate_thresholds().max_p95_ms == 180_000


def test_repo_env_retrieval_budget_stays_within_settings_contract() -> None:
    raw_value = _read_env_assignment("RETRIEVAL_MAX_TOP_K")
    if raw_value is None:
        return

    max_allowed = Settings.model_fields["retrieval_max_top_k"].default
    assert int(raw_value) <= max_allowed


def test_rerank_placeholder_defaults_are_treated_as_unconfigured() -> None:
    default_settings = Settings(_env_file=None)
    configured_settings = Settings(
        _env_file=None,
        retrieval_rerank_base_url="https://rerank.example.com",
        retrieval_rerank_api_key="secret-key",
        retrieval_rerank_model="bge-reranker",
    )

    assert default_settings.retrieval_rerank_configured is False
    assert configured_settings.retrieval_rerank_configured is True
