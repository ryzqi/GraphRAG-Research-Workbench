from types import SimpleNamespace

from langchain.agents.middleware import SummarizationMiddleware

from app.agents import general_chat_agent
from app.core.settings import Settings
from app.services.conversation_summary_service import (
    ConversationSummaryService,
    resolve_summary_trim_tokens,
)


def test_summary_settings_defaults_are_budget_aligned() -> None:
    fields = Settings.model_fields

    assert fields["summary_enabled"].default is True
    assert fields["summary_trigger_min_tokens"].default == 2_000
    assert fields["summary_keep_messages"].default == 20
    assert fields["summary_max_tokens"].default == 400
    assert fields["summary_trim_tokens"].default == 4_000


def test_general_chat_summarization_middleware_uses_settings_keep_and_trim(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(general_chat_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        general_chat_agent.CheckpointManager,
        "get_checkpointer",
        lambda: None,
    )

    general_chat_agent.build_general_chat_agent(
        chat_model=SimpleNamespace(_llm_type="fake-chat-model"),
        tools=[],
        system_prompt="system",
        summary_trigger=("tokens", 2_000),
        summary_keep_messages=12,
        summary_trim_tokens=3_000,
        tool_context_trigger_tokens=2_000,
    )

    middleware = captured["middleware"]
    assert isinstance(middleware, list)
    summarizer = next(
        item for item in middleware if isinstance(item, SummarizationMiddleware)
    )

    assert summarizer.keep == ("messages", 12)
    assert summarizer.trim_tokens_to_summarize == 3_000


def test_conversation_summary_service_uses_trim_tokens_before_summarizing() -> None:
    service = ConversationSummaryService(
        db=SimpleNamespace(),
        settings=SimpleNamespace(
            summary_trigger_min_messages=12,
            summary_trigger_min_tokens=2_000,
            summary_trim_tokens=4_000,
        ),
    )

    assert service._summary_trim_tokens() == 4_000


def test_summary_trim_tokens_can_be_disabled() -> None:
    assert resolve_summary_trim_tokens(SimpleNamespace(summary_trim_tokens=0)) is None
    assert resolve_summary_trim_tokens(SimpleNamespace(summary_trim_tokens=None)) is None
