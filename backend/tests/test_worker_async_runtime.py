from __future__ import annotations

import asyncio


def test_worker_async_runtime_reuses_same_loop_across_calls() -> None:
    from app.worker.async_runtime import (  # noqa: PLC0415
        initialize_worker_async_runtime,
        run_in_worker_async_runtime,
        shutdown_worker_async_runtime,
    )

    initialize_worker_async_runtime()
    try:
        loop_ids: list[int] = []

        async def _capture_loop() -> int:
            loop_id = id(asyncio.get_running_loop())
            loop_ids.append(loop_id)
            return loop_id

        first = run_in_worker_async_runtime(_capture_loop())
        second = run_in_worker_async_runtime(_capture_loop())

        assert first == second
        assert loop_ids == [first, second]
    finally:
        shutdown_worker_async_runtime()
