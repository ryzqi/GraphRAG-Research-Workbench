import pytest

from app.services.query_rewrite_service import QueryRewriteService


class DummyRewriteService(QueryRewriteService):
    async def _call_llm(self, prompt: str) -> str:
        return ""


@pytest.mark.asyncio
async def test_query_rewrite_empty_output_fallback() -> None:
    service = DummyRewriteService()
    result = await service.rewrite("测试问题")

    assert result.query == "测试问题"
    assert result.rewritten is False
    assert result.reason == "empty_output"
