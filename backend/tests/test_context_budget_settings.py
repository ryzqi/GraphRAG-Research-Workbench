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


def test_context_builder_metrics_include_utilization_and_truncation_rates() -> None:
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
            "summary": {"tokens": 128, "chars": 400},
            "history": {"tokens": 2_000, "chars": 6_000, "messages": 4},
        },
        history_truncation={
            "summary": {"truncated": False, "dropped_tokens": 0},
            "history": {
                "truncated": True,
                "dropped_messages": 2,
                "dropped_tokens": 500,
            },
        },
        retrieval_usage={"tokens": 8_000, "chars": 24_000, "items": 8},
        retrieval_truncation={
            "truncated": True,
            "dropped_items": 2,
            "dropped_tokens": 4_000,
        },
        tool_usage={"tokens": 500, "chars": 1_600, "items": 3},
        tool_truncation={
            "truncated": False,
            "dropped_items": 0,
            "dropped_tokens": 0,
        },
    )

    assert metrics["derived"]["context_utilization"]["history_tokens"] == 0.5
    assert metrics["derived"]["context_utilization"]["retrieval_tokens"] == 0.5
    assert metrics["derived"]["context_utilization"]["tool_tokens"] == 0.25
    assert metrics["derived"]["context_utilization"]["summary_tokens"] == 0.5
    assert metrics["derived"]["context_utilization"]["llm_input_tokens"] == 0.1328
    assert metrics["derived"]["truncation_rate"]["history"] == 0.2
    assert metrics["derived"]["truncation_rate"]["retrieval"] == 0.3333
    assert metrics["derived"]["truncation_rate"]["tools"] == 0.0
    assert metrics["derived"]["overall_truncated"] is True


def test_context_builder_metrics_tolerate_history_only_inputs() -> None:
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
            "history": {"tokens": 600, "chars": 1_800, "messages": 2},
        },
        history_truncation={
            "history": {
                "truncated": False,
                "dropped_messages": 0,
                "dropped_tokens": 0,
            },
        },
    )

    assert metrics["usage"]["summary"]["tokens"] == 0
    assert metrics["derived"]["context_utilization"]["history_tokens"] == 0.15
    assert metrics["derived"]["context_utilization"]["summary_tokens"] == 0.0
    assert metrics["derived"]["overall_truncated"] is False
