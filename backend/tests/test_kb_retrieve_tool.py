import uuid

import pytest

from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.services.retrieval_service import RetrievedChunk, RetrievalResult


class FakeRetrievalService:
    def __init__(self, results: list[RetrievalResult]) -> None:
        self._results = results
        self.calls: list[dict] = []

    async def retrieve(
        self, *, query: str, kb_ids: list[uuid.UUID], top_k: int | None = None
    ) -> list[RetrievalResult]:
        self.calls.append({"query": query, "kb_ids": kb_ids, "top_k": top_k})
        return self._results


@pytest.mark.asyncio
async def test_kb_retrieve_formats_numbered_context_and_calls_callback() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunks = [
        RetrievedChunk(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            content="第一段",
            context=None,
            locator={"page": 1},
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
        ),
        RetrievedChunk(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            content="第二段",
            context=None,
            locator={"page": 2},
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
        ),
    ]
    results = [
        RetrievalResult(chunk=chunks[0], score=0.1),
        RetrievalResult(chunk=chunks[1], score=0.2),
    ]
    retrieval = FakeRetrievalService(results)

    captured: dict = {}

    def on_results(included: list[RetrievalResult], meta: dict) -> None:
        captured["texts"] = [r.chunk.content for r in included]
        captured["meta"] = meta

    tool = build_kb_retrieve_tool(
        retrieval=retrieval,
        default_kb_ids=[kb_id],
        context_builder=None,
        on_results=on_results,
        tool_output_max_chars=10_000,
    )

    out = await tool.ainvoke({"query": "你好", "kb_ids": ["not-a-uuid"], "top_k": 2})

    assert "[1] 第一段" in out
    assert "[2] 第二段" in out
    assert retrieval.calls
    assert retrieval.calls[0]["kb_ids"] == [kb_id]
    assert captured["texts"] == ["第一段", "第二段"]
    assert captured["meta"]["count"] == 2


class FakeContextBuilder:
    def build_retrieval_context(
        self, results: list[RetrievalResult]
    ) -> tuple[str, list[RetrievalResult], dict, dict]:
        # 模拟 ContextBuilder 的返回结构
        return (
            "[1] 自定义片段",
            results[:1],
            {"tokens": 10, "chars": 12, "items": 1},
            {"truncated": True, "dropped_items": 1, "dropped_tokens": 5},
        )


@pytest.mark.asyncio
async def test_kb_retrieve_appends_truncation_mark_from_context_builder() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk = RetrievedChunk(
        id=uuid.uuid4(),
        kb_id=kb_id,
        material_id=material_id,
        content="内容",
        context=None,
        locator=None,
        metadata=None,
        chunk_role="default",
        parent_chunk_id=None,
        child_seq=None,
    )
    results = [RetrievalResult(chunk=chunk, score=0.1)]
    retrieval = FakeRetrievalService(results)

    captured: dict = {}

    def on_results(included: list[RetrievalResult], meta: dict) -> None:
        captured["count"] = len(included)
        captured["meta"] = meta

    tool = build_kb_retrieve_tool(
        retrieval=retrieval,
        default_kb_ids=[kb_id],
        context_builder=FakeContextBuilder(),
        on_results=on_results,
        tool_output_max_chars=10_000,
    )

    out = await tool.ainvoke({"query": "q"})

    assert out.endswith("（输出已截断）")
    assert captured["count"] == 1
    assert captured["meta"]["truncation"]["truncated"] is True
