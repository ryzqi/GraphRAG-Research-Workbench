from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from concurrent.futures import Future
from dataclasses import dataclass
import threading
from typing import TypeVar

from app.core.uvicorn_loop import windows_selector_loop_factory

_T = TypeVar("_T")


@dataclass(slots=True)
class _WorkerAsyncRuntimeState:
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    ready: threading.Event


_RUNTIME_LOCK = threading.Lock()
_RUNTIME_STATE: _WorkerAsyncRuntimeState | None = None


def _runtime_thread_main(ready: threading.Event) -> None:
    global _RUNTIME_STATE

    loop = windows_selector_loop_factory()
    asyncio.set_event_loop(loop)

    with _RUNTIME_LOCK:
        state = _RUNTIME_STATE
        if state is not None:
            state.loop = loop
        ready.set()

    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def initialize_worker_async_runtime() -> None:
    global _RUNTIME_STATE

    with _RUNTIME_LOCK:
        state = _RUNTIME_STATE
        if state is not None and state.thread.is_alive():
            return

        ready = threading.Event()
        loop = windows_selector_loop_factory()
        thread = threading.Thread(
            target=_runtime_thread_main,
            args=(ready,),
            name="worker-async-runtime",
            daemon=True,
        )
        _RUNTIME_STATE = _WorkerAsyncRuntimeState(
            loop=loop,
            thread=thread,
            ready=ready,
        )
        thread.start()

    ready.wait(timeout=5.0)


def _require_worker_async_runtime() -> _WorkerAsyncRuntimeState:
    initialize_worker_async_runtime()
    state = _RUNTIME_STATE
    if state is None or not state.thread.is_alive():
        raise RuntimeError("worker async runtime 未初始化")
    return state


def is_running_in_worker_async_runtime() -> bool:
    state = _RUNTIME_STATE
    if state is None or not state.thread.is_alive():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return loop is state.loop


def run_in_worker_async_runtime(awaitable: Awaitable[_T]) -> _T:
    state = _require_worker_async_runtime()
    future: Future[_T] = asyncio.run_coroutine_threadsafe(awaitable, state.loop)
    return future.result()


def shutdown_worker_async_runtime() -> None:
    global _RUNTIME_STATE

    with _RUNTIME_LOCK:
        state = _RUNTIME_STATE
        _RUNTIME_STATE = None

    if state is None or not state.thread.is_alive():
        return

    state.loop.call_soon_threadsafe(state.loop.stop)
    state.thread.join(timeout=5.0)
