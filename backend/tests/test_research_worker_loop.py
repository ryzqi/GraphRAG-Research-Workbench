from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

from app.core.uvicorn_loop import windows_selector_loop_factory
from app.worker.tasks import research as research_task


def test_research_worker_uses_windows_compatible_loop_factory(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_research_session(session_id: str) -> None:
        captured["session_id"] = session_id

    def fake_asyncio_run(
        coro: Coroutine[Any, Any, None],
        *,
        loop_factory=None,
    ) -> None:
        captured["loop_factory"] = loop_factory
        coro.close()

    monkeypatch.setattr(
        research_task,
        "_run_research_session",
        fake_run_research_session,
    )
    monkeypatch.setattr(research_task.asyncio, "run", fake_asyncio_run)

    research_task.run_research_session("fb64f8f3-1897-4ec1-9d7f-1f07f635e32d")

    assert captured["loop_factory"] is windows_selector_loop_factory
