from __future__ import annotations

from types import SimpleNamespace
import uuid

from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievedChunk, RetrievalResult


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        context_history_max_messages=6,
        context_history_max_tokens=None,
        summary_max_tokens=None,
        context_tool_max_tokens=None,
    )


def _retrieval_result(text: str) -> RetrievalResult:
    return RetrievalResult(
        chunk=RetrievedChunk(
            id=uuid.uuid4(),
            kb_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            content=text,
            context=None,
            locator=None,
            metadata={},
            chunk_role=None,
            parent_chunk_id=None,
            child_seq=None,
        ),
        score=0.9,
        context_text=None,
    )


def test_build_retrieval_context_does_not_require_removed_retrieval_token_budget() -> None:
    builder = ContextBuilder(settings=_settings())
    results = [_retrieval_result("第一段证据"), _retrieval_result("第二段证据")]

    context, included, usage, truncation = builder.build_retrieval_context(results)

    assert context.count("[S") == 2
    assert len(included) == 2
    assert usage["items"] == 2
    assert truncation == {
        "truncated": False,
        "dropped_items": 0,
        "dropped_tokens": 0,
    }


def test_build_metrics_omits_removed_retrieval_token_budget_key() -> None:
    builder = ContextBuilder(settings=_settings())

    metrics = builder.build_metrics(
        history_usage={
            "summary": {"tokens": 0, "chars": 0},
            "history": {"tokens": 3, "chars": 12},
        },
        history_truncation={
            "summary": {"truncated": False, "dropped_tokens": 0},
            "history": {"truncated": False, "dropped_tokens": 0},
        },
        retrieval_usage={"tokens": 4, "chars": 20, "items": 1},
        retrieval_truncation={"truncated": False, "dropped_items": 0, "dropped_tokens": 0},
    )

    assert "retrieval_tokens" not in metrics["budgets"]
