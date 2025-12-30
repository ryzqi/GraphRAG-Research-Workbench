from types import SimpleNamespace

from app.core.settings import Settings
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalResult


def test_history_budget_and_summary_truncation() -> None:
    settings = Settings(context_history_max_messages=2, summary_max_tokens=2)
    builder = ContextBuilder(settings)
    history = [
        LLMMessage(role="user", content="h1"),
        LLMMessage(role="assistant", content="h2"),
        LLMMessage(role="user", content="h3"),
    ]
    messages, usage, truncation = builder.build_history_messages(
        history=history, summary_text="summary " * 10
    )

    assert messages[0].role == "system"
    assert messages[1].content == "h2"
    assert messages[2].content == "h3"
    assert usage["history"]["messages"] == 2
    assert truncation["summary"]["truncated"] is True
    assert truncation["history"]["truncated"] is True


def test_retrieval_context_budget_truncates_text() -> None:
    settings = Settings(context_retrieval_max_tokens=2)
    builder = ContextBuilder(settings)
    chunk = SimpleNamespace(text="abcdefghij", token_count=None)
    results = [RetrievalResult(chunk=chunk, score=0.9)]

    context, included, usage, truncation = builder.build_retrieval_context(results)

    assert included
    assert usage["items"] == 1
    assert truncation["truncated"] is True
    assert context.startswith("[1]")
