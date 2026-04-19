from types import SimpleNamespace

from app.core.settings import Settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.services.context_builder import ContextBuilder
from app.services.general_chat_service_runtime import _build_summary_trigger


def test_settings_defaults_enable_context_budgets() -> None:
    fields = Settings.model_fields

    assert fields["llm_max_input_tokens"].default == 80_000
    assert fields["context_history_max_tokens"].default == 4_000
    assert fields["context_tool_max_tokens"].default == 2_000
    assert fields["context_retrieval_max_tokens"].default == 16_000


def test_build_chat_model_profile_uses_default_input_budget() -> None:
    profile = build_chat_model_profile(SimpleNamespace(llm_max_input_tokens=80_000))

    assert profile == {"max_input_tokens": 80_000}


def test_default_input_budget_switches_general_chat_summary_trigger_to_fraction() -> None:
    runtime = SimpleNamespace(
        _settings=SimpleNamespace(
            llm_max_input_tokens=Settings.model_fields["llm_max_input_tokens"].default,
            summary_trigger_min_messages=Settings.model_fields[
                "summary_trigger_min_messages"
            ].default,
            summary_trigger_min_tokens=Settings.model_fields[
                "summary_trigger_min_tokens"
            ].default,
        )
    )

    assert _build_summary_trigger(runtime) == ("fraction", 0.7)


def test_context_builder_metrics_expose_retrieval_and_llm_budgets() -> None:
    builder = ContextBuilder(
        SimpleNamespace(
            llm_max_input_tokens=80_000,
            context_history_max_messages=6,
            context_history_max_tokens=4_000,
            context_tool_max_tokens=2_000,
            context_retrieval_max_tokens=16_000,
            summary_max_tokens=256,
        )
    )

    metrics = builder.build_metrics(
        history_usage={
            "summary": {"tokens": 0, "chars": 0},
            "history": {"tokens": 0, "chars": 0, "messages": 0},
        },
        history_truncation={
            "summary": {"truncated": False, "dropped_tokens": 0},
            "history": {
                "truncated": False,
                "dropped_messages": 0,
                "dropped_tokens": 0,
            },
        },
    )

    assert metrics["budgets"]["llm_input_tokens"] == 80_000
    assert metrics["budgets"]["retrieval_tokens"] == 16_000
