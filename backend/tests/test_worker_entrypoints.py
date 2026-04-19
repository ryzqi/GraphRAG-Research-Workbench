from __future__ import annotations

import asyncio
import importlib
import inspect

import pytest


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "handler_name", "call_args", "expected_args", "expected_kwargs"),
    [
        (
            "app.worker.tasks.export",
            "run_export",
            "_run_export",
            ("export-id", "research", "target-id"),
            (),
            {
                "export_id": "export-id",
                "export_type": "research",
                "target_id": "target-id",
            },
        ),
        (
            "app.worker.tasks.ingestion_batches",
            "run_ingestion_batch_doc",
            "_run_ingestion_batch_doc",
            ("doc-id",),
            ("doc-id",),
            {},
        ),
        (
            "app.worker.tasks.ingestion_outbox_dispatcher",
            "dispatch_ingestion_outbox",
            "_dispatch_ingestion_outbox",
            (7,),
            (),
            {"limit": 7},
        ),
        (
            "app.worker.tasks.index_rebuild",
            "run_index_rebuild_job",
            "_run_index_rebuild_job",
            ("job-id",),
            ("job-id",),
            {},
        ),
        (
            "app.worker.tasks.index_rebuild_outbox_dispatcher",
            "dispatch_index_rebuild_outbox",
            "_dispatch_index_rebuild_outbox",
            (11,),
            (),
            {"limit": 11},
        ),
        (
            "app.worker.tasks.bootstrap_watchdog",
            "fail_stale_bootstrap_jobs",
            "_fail_stale_bootstrap_jobs",
            (3,),
            (),
            {"limit": 3},
        ),
        (
            "app.worker.tasks.ingestion_watchdog",
            "fail_stale_processing_docs",
            "_fail_stale_processing_docs",
            (5,),
            (),
            {"limit": 5},
        ),
        (
            "app.worker.tasks.research",
            "run_research_session",
            "_run_research_session",
            ("session-id",),
            ("session-id",),
            {},
        ),
        (
            "app.worker.tasks.research_outbox_dispatcher",
            "dispatch_research_outbox",
            "_dispatch_research_outbox",
            (9,),
            (),
            {"limit": 9},
        ),
    ],
)
def test_worker_sync_entrypoints_submit_coroutines_via_shared_runtime(
    monkeypatch,
    module_name: str,
    entrypoint_name: str,
    handler_name: str,
    call_args: tuple[object, ...],
    expected_args: tuple[object, ...],
    expected_kwargs: dict[str, object],
) -> None:
    module = importlib.import_module(module_name)
    original_asyncio_run = asyncio.run
    handler_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    runtime_call_count = 0

    async def _fake_handler(*args: object, **kwargs: object) -> None:
        handler_calls.append((args, dict(kwargs)))

    def _fake_run_in_worker_async_runtime(awaitable):
        nonlocal runtime_call_count
        runtime_call_count += 1
        return original_asyncio_run(awaitable)

    def _unexpected_asyncio_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("同步 worker 入口不应继续直接调用 asyncio.run")

    monkeypatch.setattr(module, handler_name, _fake_handler)
    monkeypatch.setattr(
        module,
        "run_in_worker_async_runtime",
        _fake_run_in_worker_async_runtime,
        raising=False,
    )
    monkeypatch.setattr(asyncio, "run", _unexpected_asyncio_run)

    getattr(module, entrypoint_name)(*call_args)

    assert runtime_call_count == 1
    assert handler_calls == [(expected_args, expected_kwargs)]


def test_worker_process_hooks_use_shared_runtime(monkeypatch) -> None:
    from app.worker import celery_app as celery_app_module

    runtime_calls: list[object] = []

    def _fake_run_in_worker_async_runtime(awaitable):
        runtime_calls.append(awaitable)
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        return None

    def _unexpected_asyncio_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker process hook 不应继续直接调用 asyncio.run")

    monkeypatch.setattr(
        celery_app_module,
        "run_in_worker_async_runtime",
        _fake_run_in_worker_async_runtime,
        raising=False,
    )
    monkeypatch.setattr(asyncio, "run", _unexpected_asyncio_run)

    celery_app_module._prewarm_deep_research_runtime()
    celery_app_module._shutdown_deep_research_runtime_cache()

    assert len(runtime_calls) == 2
    assert all(inspect.iscoroutine(awaitable) for awaitable in runtime_calls)
