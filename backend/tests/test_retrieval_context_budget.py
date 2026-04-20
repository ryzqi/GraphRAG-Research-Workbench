from types import SimpleNamespace
import uuid

from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalResult, RetrievedChunk


def _result(text: str, *, score: float = 1.0) -> RetrievalResult:
    chunk = RetrievedChunk(
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
    )
    return RetrievalResult(chunk=chunk, score=score)


def _settings(max_tokens: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        context_retrieval_max_tokens=max_tokens,
    )


def test_retrieval_context_respects_token_budget_by_rank_order() -> None:
    builder = ContextBuilder(_settings(4))
    results = [
        _result("A" * 8, score=0.9),
        _result("B" * 8, score=0.8),
        _result("C" * 40, score=0.7),
    ]

    context, included, usage, truncation = builder.build_retrieval_context(results)

    assert included == results[:2]
    assert "[S1]" in context
    assert "[S2]" in context
    assert "[S3]" not in context
    assert usage["items"] == 2
    assert usage["tokens"] <= 4
    assert truncation["truncated"] is True
    assert truncation["dropped_items"] == 1
    assert truncation["dropped_tokens"] > 0


def test_retrieval_context_truncates_top_result_when_budget_is_tighter_than_one_item() -> None:
    builder = ContextBuilder(_settings(2))
    results = [
        _result("A" * 40, score=0.9),
        _result("B" * 8, score=0.8),
    ]

    context, included, usage, truncation = builder.build_retrieval_context(results)

    assert included == results[:1]
    assert "[S1]" in context
    assert "B" not in context
    assert usage["items"] == 1
    assert usage["tokens"] <= 2
    assert truncation["truncated"] is True
    assert truncation["dropped_items"] == 1
    assert truncation["dropped_tokens"] > 0
