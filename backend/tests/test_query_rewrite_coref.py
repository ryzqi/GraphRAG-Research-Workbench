import types

import pytest

from app.services.query_rewrite_service import QueryRewriteService


@pytest.fixture
def settings():
    return types.SimpleNamespace(
        retrieval_query_rewrite_timeout_seconds=15,
        retrieval_query_rewrite_max_tokens=64,
        kb_chat_ambiguity_check_enabled=True,
        kb_chat_hyde_enabled=False,
    )


@pytest.mark.asyncio
async def test_coref_rewrite_resolves_recent_turn_reference(settings):
    svc = QueryRewriteService(settings=settings)

    result = await svc.coref_rewrite(
        "这个流程怎么配置？",
        recent_turns=[
            {"role": "user", "text": "请介绍 OAuth 登录流程"},
            {"role": "assistant", "text": "可以从回调地址和授权范围开始配置"},
        ],
        summary_text="",
        memory_snippet="",
    )

    assert result.rewritten is True
    assert "OAuth 登录流程" in result.query
    assert isinstance(result.meta, dict)
    assert float(result.meta.get("confidence", 0.0)) >= 0.72
    assert result.meta.get("needs_clarification") is False


@pytest.mark.asyncio
async def test_coref_rewrite_keeps_query_when_low_confidence(settings):
    svc = QueryRewriteService(settings=settings)

    result = await svc.coref_rewrite(
        "这个怎么样",
        recent_turns=[],
        summary_text="",
        memory_snippet="",
    )

    assert result.query == "这个怎么样"
    assert result.rewritten is False
    assert isinstance(result.meta, dict)
    assert result.meta.get("needs_clarification") is True
    assert result.reason in {"no_candidate", "low_confidence", "unchanged_after_apply"}
