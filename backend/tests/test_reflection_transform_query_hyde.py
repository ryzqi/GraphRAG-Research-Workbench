import pytest

from app.agents.kb_chat_agentic.reflection import transform_query_for_retry
from app.services.query_rewrite_service import QueryListResult, RewriteResult


@pytest.mark.asyncio
async def test_transform_query_for_retry_regenerates_hyde(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeRewriteService:
        def __init__(self, settings=None) -> None:  # type: ignore[no-untyped-def]
            pass

        async def transform_query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return RewriteResult(query="改写后问题", rewritten=True, reason="ok")

        async def hyde(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return QueryListResult(
                queries=["假设文档A", "假设文档B"], success=True, reason="llm_structured"
            )

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection.QueryRewriteService",
        _FakeRewriteService,
    )

    state = {
        "normalized_query": "原问题",
        "coref_query": "原问题",
        "merged_context": "原问题",
        "user_input": "原问题",
        "loop_counts": {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0},
        "runtime_config": {"query_rewrite_enabled": True, "hyde_enabled": True},
        "reflection": {"reason": "insufficient", "hint": "补充约束"},
        "stage_summaries": {},
    }

    settings = type(
        "S",
        (),
        {
            "kb_chat_max_retrieval_retries": 2,
            "kb_chat_json_safe_policy": "stringify",
            "kb_chat_hyde_enabled": False,
            "retrieval_query_rewrite_enabled": True,
        },
    )()

    update = await transform_query_for_retry(state, settings=settings)  # type: ignore[arg-type]

    assert update["normalized_query"] == "改写后问题"
    assert update["hyde_doc"] == "假设文档A"
    assert update["hyde_docs"] == ["假设文档A", "假设文档B"]

    hyde_item = next(
        item
        for item in update["query_items"]  # type: ignore[index]
        if isinstance(item, dict) and item.get("kind") == "hyde"
    )
    assert hyde_item.get("note") == "retry_regenerated"
