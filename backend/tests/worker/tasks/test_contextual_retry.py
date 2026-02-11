from __future__ import annotations

import pytest

from app.services.contextual_embedding_service import ContextResult
from app.worker.tasks.contextual_retry import generate_contexts_for_chunks


class _FakeContextService:
    def __init__(self, results: list[ContextResult]) -> None:
        self._results = results
        self._calls = 0

    async def generate(self, **_kwargs: object) -> ContextResult:
        index = min(self._calls, len(self._results) - 1)
        self._calls += 1
        return self._results[index]


@pytest.mark.asyncio
async def test_context_retry_falls_back_to_empty_raw_context() -> None:
    service = _FakeContextService(
        [ContextResult(context="", success=False, reason="empty_output")]
    )

    results = await generate_contexts_for_chunks(
        full_text="全量文档",
        chunk_texts=["chunk-1"],
        context_service=service,
        enabled=True,
        max_tokens=64,
        concurrency=1,
        max_attempts=3,
    )

    assert len(results) == 1
    item = results[0]
    assert item.status == "fallback"
    assert item.context == ""
    assert item.error == "empty_output"
    assert item.attempts == 3


@pytest.mark.asyncio
async def test_context_retry_keeps_success_result() -> None:
    service = _FakeContextService(
        [
            ContextResult(context="", success=False, reason="empty_output"),
            ContextResult(context="增强上下文", success=True, reason=None),
        ]
    )

    results = await generate_contexts_for_chunks(
        full_text="全量文档",
        chunk_texts=["chunk-1"],
        context_service=service,
        enabled=True,
        max_tokens=64,
        concurrency=1,
        max_attempts=3,
    )

    assert len(results) == 1
    item = results[0]
    assert item.status == "success"
    assert item.context == "增强上下文"
    assert item.error is None
    assert item.attempts == 2


@pytest.mark.asyncio
async def test_context_retry_reports_not_enabled() -> None:
    service = _FakeContextService([ContextResult(context="x", success=True)])

    results = await generate_contexts_for_chunks(
        full_text="全量文档",
        chunk_texts=["chunk-1"],
        context_service=service,
        enabled=False,
        max_tokens=64,
        concurrency=1,
        max_attempts=3,
    )

    assert len(results) == 1
    item = results[0]
    assert item.status == "not_enabled"
    assert item.context == ""
    assert item.error is None
    assert item.attempts == 0
