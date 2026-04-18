import asyncio
from unittest.mock import MagicMock

from langchain_core.documents import Document

from app.search.web.pipeline import WebSearchPipeline


class _SlowRetriever:
    def __init__(self, name: str, delay: float = 0.05) -> None:
        self.provider_name = name
        self.delay = delay
        self.call_times: list[float] = []

    async def aretrieve(self, query, **_kwargs):
        self.call_times.append(asyncio.get_running_loop().time())
        await asyncio.sleep(self.delay)
        return [Document(page_content=f"{self.provider_name}:{query}", metadata={})]


async def test_pipeline_runs_query_retriever_matrix_in_parallel(monkeypatch) -> None:
    retrievers = [_SlowRetriever(f"r{i}", delay=0.05) for i in range(3)]
    pipeline = WebSearchPipeline(retrievers=retrievers)

    class _FakeSettings:
        web_search_pipeline_max_concurrency = 8

    monkeypatch.setattr(
        "app.search.web.pipeline.get_settings",
        lambda: _FakeSettings(),
        raising=False,
    )

    def _plan(query: str, **_kwargs: object) -> MagicMock:
        plan = MagicMock()
        plan.original_query = query
        plan.rewritten_queries = ["q1", "q2", "q3"]
        return plan

    monkeypatch.setattr("app.search.web.pipeline.build_search_query_plan", _plan)

    async def _noop_enrich(docs, *, read_provider=None):
        return docs, None

    monkeypatch.setattr("app.search.web.pipeline.enrich_documents", _noop_enrich)
    monkeypatch.setattr(
        "app.search.web.pipeline.fuse_documents",
        lambda groups, max_results: [document for group in groups for document in group],
    )
    monkeypatch.setattr(
        "app.search.web.pipeline.rerank_documents",
        lambda docs, query, max_results: docs,
    )

    start = asyncio.get_running_loop().time()
    result = await pipeline.search(query="x", max_results=3)
    elapsed = asyncio.get_running_loop().time() - start

    assert result["merged_count"] == 9
    assert elapsed < 0.25, f"太慢：{elapsed:.3f}s，说明还是串行"


async def test_pipeline_concurrency_limited_by_setting(monkeypatch) -> None:
    retrievers = [_SlowRetriever(f"r{i}", delay=0.05) for i in range(2)]
    pipeline = WebSearchPipeline(retrievers=retrievers)

    class _FakeSettings:
        web_search_pipeline_max_concurrency = 2

    monkeypatch.setattr(
        "app.search.web.pipeline.get_settings",
        lambda: _FakeSettings(),
        raising=False,
    )

    def _plan(query: str, **_kwargs: object) -> MagicMock:
        plan = MagicMock()
        plan.original_query = query
        plan.rewritten_queries = ["q1", "q2", "q3"]
        return plan

    monkeypatch.setattr("app.search.web.pipeline.build_search_query_plan", _plan)

    async def _noop_enrich(docs, *, read_provider=None):
        return docs, None

    monkeypatch.setattr("app.search.web.pipeline.enrich_documents", _noop_enrich)
    monkeypatch.setattr(
        "app.search.web.pipeline.fuse_documents",
        lambda groups, max_results: [document for group in groups for document in group],
    )
    monkeypatch.setattr(
        "app.search.web.pipeline.rerank_documents",
        lambda docs, query, max_results: docs,
    )

    start = asyncio.get_running_loop().time()
    await pipeline.search(query="x", max_results=3)
    elapsed = asyncio.get_running_loop().time() - start

    assert 0.12 < elapsed < 0.28, f"并发度未被限制：{elapsed:.3f}s"
