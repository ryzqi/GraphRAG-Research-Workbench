from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_observability import classify_research_fault
from app.services.research_planner import ResearchPlanner
from app.services.research_service import ResearchService


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


class _UnusedRuntimeRunner:
    async def run_session(self, **_: object) -> object:
        raise AssertionError("本测试不应调用 runtime")


@pytest.mark.parametrize(
    ("label", "exc_factory", "source_provider", "expected_category"),
    [
        (
            "db_jitter",
            lambda: OperationalError("SELECT 1", {}, Exception("db jitter")),
            None,
            "db_jitter",
        ),
        (
            "redis_unavailable",
            lambda: RedisConnectionError("redis down"),
            None,
            "redis_unavailable",
        ),
        (
            "tavily_timeout",
            lambda: asyncio.TimeoutError(),
            "tavily",
            "timeout",
        ),
        (
            "jina_timeout",
            lambda: httpx.ReadTimeout(
                "read timeout",
                request=httpx.Request("GET", "https://r.jina.ai/http://example.com"),
            ),
            "jina_reader",
            "timeout",
        ),
        (
            "searxng_timeout",
            lambda: httpx.ReadTimeout(
                "read timeout",
                request=httpx.Request("GET", "http://127.0.0.1:18080/search"),
            ),
            "searxng",
            "timeout",
        ),
        (
            "arxiv_timeout",
            lambda: httpx.ReadTimeout(
                "read timeout",
                request=httpx.Request("GET", "https://export.arxiv.org/api/query"),
            ),
            "arxiv",
            "timeout",
        ),
        (
            "provider_429",
            lambda: httpx.HTTPStatusError(
                "rate limited",
                request=httpx.Request("GET", "https://api.tavily.com/search"),
                response=httpx.Response(
                    429,
                    request=httpx.Request("GET", "https://api.tavily.com/search"),
                ),
            ),
            "tavily",
            "rate_limited",
        ),
        (
            "provider_unreachable",
            lambda: httpx.ConnectError(
                "connection refused",
                request=httpx.Request("GET", "http://127.0.0.1:18080/search"),
            ),
            "searxng",
            "instance_unreachable",
        ),
        (
            "malformed_response",
            lambda: json.JSONDecodeError("bad json", "{", 1),
            "arxiv",
            "malformed_response",
        ),
    ],
)
async def test_fail_session_records_fault_metrics_and_failure_event(
    label: str,
    exc_factory,
    source_provider: str | None,
    expected_category: str,
) -> None:
    del label
    service = ResearchService(
        db=_FakeAsyncSession(),
        planner=ResearchPlanner(),
        runtime_runner=_UnusedRuntimeRunner(),
        finalizer=ResearchFinalizer(),
    )
    session = ResearchSession(
        id=uuid4(),
        thread_id="research-fault-session",
        question="验证故障注入分类",
        status=ResearchSessionStatus.RUNNING,
        trace_id="trace-research-fault",
    )

    exc = exc_factory()
    await service.fail_session(
        session=session,
        exc=exc,
        phase="runtime",
        source_provider=source_provider,
    )

    fault = classify_research_fault(exc, source_provider=source_provider)
    assert fault["category"] == expected_category
    assert session.status == ResearchSessionStatus.FAILED
    assert session.events[-1].event_type == "research.run.failed"
    assert session.events[-1].payload["fault"]["category"] == expected_category
    assert (session.metrics or {})["faults"]["records"][-1]["category"] == expected_category
    if source_provider is not None:
        assert (session.metrics or {})["faults"]["by_source_provider"][source_provider]["count"] >= 1
    assert (session.metrics or {})["gate"]["pass"] is False
