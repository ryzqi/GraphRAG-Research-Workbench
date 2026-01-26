import json
import time
import uuid

import pytest

from app.agents.kb_chat_agentic.json_safety import ensure_json_safe
from app.agents.kb_chat_agentic.reflection import (
    doc_grader,
    kb_retrieve_context,
    route_after_answer_check,
)
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.core.settings import Settings
from app.services.retrieval_service import (
    RetrievalResult,
    RetrievalService,
    RetrievedChunk,
)
from langchain.messages import AIMessage


class _ExplodingTool:
    name = "kb_retrieve"

    async def ainvoke(self, _payload: dict) -> str:
        raise AssertionError("kb_retrieve should not be called")


class _DummyChatModel:
    pass


@pytest.mark.asyncio
async def test_kb_retrieve_context_budget_exhausted_skips_tool() -> None:
    settings = Settings()
    state = {
        "user_input": "q",
        "metrics": {"budget": {"deadline_ts": time.time() - 1}},
    }
    updates = await kb_retrieve_context(
        state, settings=settings, kb_tool=_ExplodingTool()
    )
    assert updates["metrics"]["retrieval_layer"]["attempted"] is False
    assert updates["stage_summaries"]["retrieval_layer"]["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_doc_grader_fail_policy_closed_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_judge_json(**_kwargs: object):
        return None, "invalid_json"

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection._judge_json", _fake_judge_json
    )
    settings = Settings(kb_chat_grader_fail_policy="closed")
    state = {
        "merged_context": "q",
        "user_input": "q",
        "final_context": "[1] doc",
    }
    updates = await doc_grader(state, settings=settings, chat_model=_DummyChatModel())
    summary = updates["stage_summaries"]["doc_grader"]
    assert updates["reflection"]["relevance_passed"] is False
    assert summary["fallback_used"] is True
    assert summary["fallback_reason"] == "invalid_json"


@pytest.mark.asyncio
async def test_doc_grader_fail_policy_open_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_judge_json(**_kwargs: object):
        return None, "invalid_json"

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection._judge_json", _fake_judge_json
    )
    settings = Settings(kb_chat_grader_fail_policy="open")
    state = {
        "merged_context": "q",
        "user_input": "q",
        "final_context": "[1] doc",
    }
    updates = await doc_grader(state, settings=settings, chat_model=_DummyChatModel())
    summary = updates["stage_summaries"]["doc_grader"]
    assert updates["reflection"]["relevance_passed"] is True
    assert summary["fallback_used"] is True
    assert summary["fallback_reason"] == "invalid_json"


def test_force_retrieve_blocks_finalize() -> None:
    settings = Settings()
    state = {
        "force_kb_retrieve": True,
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "reflection": {"answer_passed": True},
        "metrics": {},
    }
    assert route_after_answer_check(state, settings) == "transform_query"


def test_json_safe_policy() -> None:
    dev_settings = Settings(app_env="dev", kb_chat_json_safe_policy="stringify")
    with pytest.raises(ValueError):
        ensure_json_safe({"x": object()}, settings=dev_settings, label="metrics")

    prod_settings = Settings(app_env="prod", kb_chat_json_safe_policy="stringify")
    safe = ensure_json_safe({"x": object()}, settings=prod_settings, label="metrics")
    json.dumps(safe)


def test_force_exit_blocks_unpassed_answer() -> None:
    settings = Settings()
    state = {
        "reflection": {"action": "force_exit", "answer_passed": False},
        "final_answer": "should_not_return",
        "draft_answer": "draft",
        "messages": [AIMessage(content="secret")],
        "stage_summaries": {},
        "metrics": {},
    }
    updates = force_exit_node(state, settings)
    assert updates["final_answer"] == "根据现有资料无法回答该问题（已停止重试）。"
    assert updates["messages"][0].content == updates["final_answer"]


def test_force_exit_allows_answer_when_passed() -> None:
    settings = Settings()
    state = {
        "reflection": {"action": "force_exit", "answer_passed": True},
        "final_answer": "ok",
        "draft_answer": "draft",
        "stage_summaries": {},
        "metrics": {},
    }
    updates = force_exit_node(state, settings)
    assert updates["final_answer"] == "ok"
    assert updates["messages"][0].content == "ok"


@pytest.mark.asyncio
async def test_rerank_timeout_budget_exhausted_skips_call() -> None:
    class _ExplodingReranker:
        async def rerank(self, **_kwargs: object):
            raise AssertionError("rerank should not be called")

    service = RetrievalService(
        db=object(),
        milvus=object(),
        embedding=object(),
        redis=None,
        reranker=_ExplodingReranker(),
    )  # type: ignore[arg-type]
    chunk = RetrievedChunk(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        content="content",
        context=None,
        locator=None,
        metadata=None,
        chunk_role=None,
        parent_chunk_id=None,
        child_seq=None,
    )
    results = [RetrievalResult(chunk=chunk, score=1.0, context_text="ctx")]
    ordered, applied, reason, _latency = await service._maybe_rerank(
        "q", results, 1, timeout_seconds=0
    )
    assert ordered == results
    assert applied is False
    assert reason == "budget_exhausted"


@pytest.mark.asyncio
async def test_retrieval_timeout_seconds_zero_short_circuits() -> None:
    class _ExplodingDb:
        async def execute(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("db execute should not be called")

    class _ExplodingMilvus:
        async def search(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("milvus search should not be called")

        async def bm25_search(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("milvus bm25 should not be called")

        async def query_by_chunk_ids(
            self, *_args: object, **_kwargs: object
        ):  # pragma: no cover
            raise AssertionError("milvus query should not be called")

    class _ExplodingEmbedding:
        async def embed(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("embedding should not be called")

    service = RetrievalService(
        db=_ExplodingDb(),
        milvus=_ExplodingMilvus(),
        embedding=_ExplodingEmbedding(),
        redis=None,
    )  # type: ignore[arg-type]
    results = await service.retrieve(
        query="q", kb_ids=[uuid.uuid4()], timeout_seconds=0
    )
    assert results == []
    assert service.last_layer_draft is not None
    assert service.last_layer_draft.stats.get("reason") == "timeout"
    assert service.last_stats is not None
    assert service.last_stats.reason == "timeout"


@pytest.mark.asyncio
async def test_retrieve_layer_timeout_seconds_zero_returns_timeout_draft() -> None:
    class _ExplodingMilvus:
        async def search(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("milvus search should not be called")

        async def bm25_search(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("milvus bm25 should not be called")

        async def query_by_chunk_ids(
            self, *_args: object, **_kwargs: object
        ):  # pragma: no cover
            raise AssertionError("milvus query should not be called")

    class _ExplodingEmbedding:
        async def embed(self, *_args: object, **_kwargs: object):  # pragma: no cover
            raise AssertionError("embedding should not be called")

    service = RetrievalService(
        db=object(),
        milvus=_ExplodingMilvus(),
        embedding=_ExplodingEmbedding(),
        redis=None,
    )  # type: ignore[arg-type]
    draft = await service.retrieve_layer(
        query_items=[{"kind": "main", "query": "q", "use_dense": True, "use_bm25": True}],
        kb_ids=[uuid.uuid4()],
        top_n=3,
        timeout_seconds=0,
    )
    assert draft.results == []
    assert draft.stats.get("reason") == "timeout"
