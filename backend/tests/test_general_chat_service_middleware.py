from __future__ import annotations

from langchain.messages import AIMessage, HumanMessage

from app.agents.tool_calling.registry import ToolMeta
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.agents.general_chat_agent import (
    SUMMARY_KEEP,
    SUMMARY_TRIGGER,
    build_hitl_decisions,
    build_interrupt_on,
    build_pending_tool_calls,
)
from app.services.general_chat_service import GeneralChatService


def _tool_meta(name: str, *, external: bool) -> ToolMeta:
    return ToolMeta(
        tool_name=name,
        raw_tool_name=f"raw_{name}",
        extension_id="ext-1" if external else "builtin",
        extension_name="external" if external else "internal",
        is_builtin=not external,
        is_external=external,
    )


def test_summary_middleware_config_constants() -> None:
    assert SUMMARY_TRIGGER == ("fraction", 0.7)
    assert SUMMARY_KEEP == ("messages", 20)


def test_interrupt_on_external_tools_only() -> None:
    tool_meta_by_name = {
        "internal_tool": _tool_meta("internal_tool", external=False),
        "external_tool": _tool_meta("external_tool", external=True),
    }

    interrupt_on = build_interrupt_on(tool_meta_by_name)

    assert interrupt_on["internal_tool"] is False
    assert interrupt_on["external_tool"]["allowed_decisions"] == ["approve", "reject"]


def test_pending_tool_calls_mapping() -> None:
    tool_meta_by_name = {
        "external_tool": _tool_meta("external_tool", external=True),
    }
    action_requests = [
        {"name": "external_tool", "arguments": {"q": "x"}},
        {"name": "unknown_tool", "arguments": {"foo": "bar"}},
    ]

    pending = build_pending_tool_calls(action_requests, tool_meta_by_name)

    assert pending[0]["tool_name"] == "raw_external_tool"
    assert pending[0]["extension_id"] == "ext-1"
    assert pending[0]["args"] == {"q": "x"}
    assert pending[1]["extension_id"] == "unknown"
    assert pending[1]["tool_name"] == "unknown_tool"


def test_hitl_decisions() -> None:
    assert build_hitl_decisions(0, True) == []
    assert build_hitl_decisions(2, True) == [
        {"type": "approve"},
        {"type": "approve"},
    ]

    rejected = build_hitl_decisions(2, False)
    assert rejected[0]["type"] == "reject"
    assert rejected[1]["type"] == "reject"


def test_build_agent_messages_multi_turn() -> None:
    history = [
        LLMMessage(role="user", content="u1"),
        LLMMessage(role="assistant", content="a1"),
    ]

    messages = GeneralChatService._build_agent_messages(history, "u2")

    assert len(messages) == 3
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "u1"
    assert isinstance(messages[1], AIMessage)
    assert messages[1].content == "a1"
    assert isinstance(messages[2], HumanMessage)
    assert messages[2].content == "u2"
