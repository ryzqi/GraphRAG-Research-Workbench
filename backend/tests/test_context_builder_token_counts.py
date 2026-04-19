from __future__ import annotations

import uuid

import pytest

from app.core.settings import Settings
from app.integrations.llm_client import ChatMessage
from app.services import chunking as chunking_module
from app.services import context_builder as context_builder_module
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service_contracts import RetrievedChunk, RetrievalResult


def _retrieval_result(text: str) -> RetrievalResult:
    return RetrievalResult(
        chunk=RetrievedChunk(
            id=uuid.uuid4(),
            kb_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            content=text,
            context=None,
            locator=None,
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
        ),
        score=0.5,
        context_text=text,
    )


def test_merge_chunk_metadata_attaches_token_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    def _fake_count_tokens(text: str, *, model: str | None = None) -> int:
        calls.append((text, model))
        return 9

    monkeypatch.setattr(chunking_module, "count_tokens", _fake_count_tokens)

    metadata = chunking_module._merge_chunk_metadata(
        {"document": "meta"},
        {"chunking_strategy": "test", "index": 0},
        content="chunk text",
    )

    assert metadata["document"] == "meta"
    assert metadata["chunking_strategy"] == "test"
    assert metadata["token_count"] == 9
    assert calls == [("chunk text", None)]


def test_context_builder_counts_each_retrieval_result_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _fake_count_tokens(text: str) -> int:
        calls.append(text)
        return len(text)

    monkeypatch.setattr(
        context_builder_module,
        "count_tokens_approximately",
        _fake_count_tokens,
    )
    builder = ContextBuilder(Settings(_env_file=None))
    results = [
        _retrieval_result("alpha"),
        _retrieval_result("beta"),
        _retrieval_result("gamma"),
    ]

    context, included, usage, truncation = builder.build_retrieval_context(results)

    assert included == results
    assert usage["tokens"] == len("alpha") + len("beta") + len("gamma")
    assert truncation["dropped_tokens"] == 0
    assert len(calls) == len(results)
    assert context.startswith("[S1] alpha")


def test_context_builder_counts_each_history_message_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _fake_count_tokens(text: str) -> int:
        calls.append(text)
        return len(text)

    monkeypatch.setattr(
        context_builder_module,
        "count_tokens_approximately",
        _fake_count_tokens,
    )
    builder = ContextBuilder(Settings(_env_file=None))
    history = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="second"),
        ChatMessage(role="user", content="third"),
    ]

    kept, usage, truncation = builder._truncate_history(
        history,
        max_messages=10,
        max_tokens=100,
    )

    assert kept == history
    assert usage["tokens"] == len("first") + len("second") + len("third")
    assert truncation["dropped_tokens"] == 0
    assert len(calls) == len(history)
