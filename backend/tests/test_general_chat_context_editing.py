from types import SimpleNamespace

from langchain.agents.middleware import ContextEditingMiddleware
from langchain.agents.middleware.context_editing import ClearToolUsesEdit

from app.agents import general_chat_agent


def test_general_chat_agent_installs_tool_context_editing_middleware(monkeypatch) -> None:
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
        summary_trigger=("messages", 12),
        tool_context_trigger_tokens=2_000,
    )

    middleware = captured["middleware"]
    assert isinstance(middleware, list)

    context_editors = [
        item for item in middleware if isinstance(item, ContextEditingMiddleware)
    ]
    assert len(context_editors) == 1

    edit = context_editors[0].edits[0]
    assert isinstance(edit, ClearToolUsesEdit)
    assert edit.trigger == 2_000
    assert edit.keep == 3
    assert edit.clear_tool_inputs is False
    assert edit.placeholder == "[cleared by context editing]"


def test_general_chat_context_editing_uses_langchain_default_when_budget_disabled(
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
        summary_trigger=("messages", 12),
        tool_context_trigger_tokens=None,
    )

    middleware = captured["middleware"]
    assert isinstance(middleware, list)
    context_editor = next(
        item for item in middleware if isinstance(item, ContextEditingMiddleware)
    )

    edit = context_editor.edits[0]
    assert isinstance(edit, ClearToolUsesEdit)
    assert edit.trigger == 100_000
