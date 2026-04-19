from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from celery import Celery
from celery.signals import setup_logging, worker_process_init, worker_process_shutdown
from kombu import Queue

from app.core.logging import configure_logging
from app.core.uvicorn_loop import windows_selector_loop_factory
from app.core.settings import Settings, get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

DEFAULT_DISPATCH_BATCH_SIZE = 50

celery_app = Celery(
    "mkb_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.worker.tasks.export",
        "app.worker.tasks.ingestion_batches",
        "app.worker.tasks.ingestion_outbox_dispatcher",
        "app.worker.tasks.ingestion_watchdog",
        "app.worker.tasks.index_rebuild",
        "app.worker.tasks.index_rebuild_outbox_dispatcher",
        "app.worker.tasks.bootstrap_watchdog",
        "app.worker.tasks.research",
        "app.worker.tasks.research_outbox_dispatcher",
    ],
)


def _resolve_optional_time_limit(seconds: int) -> int | None:
    return seconds if seconds > 0 else None


def _build_celery_conf(cfg: Settings) -> dict[str, Any]:
    conf: dict[str, Any] = {
        "broker_connection_retry_on_startup": True,
        "broker_transport_options": {
            # 保持与 Settings 一致：本仓库刻意使用 7200 秒而非
            # Celery Redis 默认的 3600 秒，以减少长任务被过早重复投递。
            "visibility_timeout": cfg.celery_broker_visibility_timeout_seconds
        },
        "accept_content": ["json"],
        "task_serializer": "json",
        "result_serializer": "json",
        "result_accept_content": ["json"],
        "task_ignore_result": True,
        "task_store_errors_even_if_ignored": cfg.celery_task_store_errors_even_if_ignored,
        "task_track_started": True,
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "task_acks_on_failure_or_timeout": True,
        "worker_send_task_events": cfg.celery_worker_send_task_events,
        "task_send_sent_event": cfg.celery_task_send_sent_event,
        "worker_prefetch_multiplier": cfg.celery_worker_prefetch_multiplier,
        "worker_hijack_root_logger": False,
        "task_default_queue": "default",
        "task_queues": (
            Queue("default"),
            Queue("dispatch"),
            Queue("ingestion"),
            Queue("rebuild"),
            Queue("research"),
            Queue("export"),
        ),
        "task_routes": {
            "app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox": {
                "queue": "dispatch"
            },
            "app.worker.tasks.index_rebuild_outbox_dispatcher.dispatch_index_rebuild_outbox": {
                "queue": "dispatch"
            },
            "app.worker.tasks.ingestion_batches.run_ingestion_batch_doc": {
                "queue": "ingestion"
            },
            "app.worker.tasks.ingestion_watchdog.fail_stale_processing_docs": {
                "queue": "dispatch"
            },
            "app.worker.tasks.index_rebuild.run_index_rebuild_job": {
                "queue": "rebuild"
            },
            "app.worker.tasks.export.run_export": {"queue": "export"},
            "app.worker.tasks.research.run_research_session": {"queue": "research"},
            "app.worker.tasks.bootstrap_watchdog.fail_stale_bootstrap_jobs": {
                "queue": "dispatch"
            },
            "app.worker.tasks.research_outbox_dispatcher.dispatch_research_outbox": {
                "queue": "dispatch"
            },
        },
        "timezone": "Asia/Shanghai",
        "beat_schedule": {
            "bootstrap-watchdog": {
                "task": "app.worker.tasks.bootstrap_watchdog.fail_stale_bootstrap_jobs",
                "schedule": timedelta(seconds=30),
                "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
            },
            "ingestion-outbox-dispatcher": {
                "task": "app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox",
                "schedule": timedelta(seconds=20),
                "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
            },
            "ingestion-doc-watchdog": {
                "task": "app.worker.tasks.ingestion_watchdog.fail_stale_processing_docs",
                "schedule": timedelta(seconds=60),
                "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
            },
            "index-rebuild-outbox-dispatcher": {
                "task": "app.worker.tasks.index_rebuild_outbox_dispatcher.dispatch_index_rebuild_outbox",
                "schedule": timedelta(seconds=30),
                "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
            },
            "research-outbox-dispatcher": {
                "task": "app.worker.tasks.research_outbox_dispatcher.dispatch_research_outbox",
                "schedule": timedelta(seconds=30),
                "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
            },
        },
    }
    soft_limit = _resolve_optional_time_limit(cfg.celery_task_soft_time_limit_seconds)
    hard_limit = _resolve_optional_time_limit(cfg.celery_task_time_limit_seconds)
    if soft_limit is not None:
        conf["task_soft_time_limit"] = soft_limit
    if hard_limit is not None:
        conf["task_time_limit"] = hard_limit
    return conf


def configure_celery_logging(level: str | None = None) -> None:
    configure_logging(level or settings.core.app_log_level)


@setup_logging.connect
def _configure_celery_logging(*args, **kwargs) -> None:
    configure_celery_logging(settings.core.app_log_level)


celery_app.conf.update(_build_celery_conf(settings))


@worker_process_init.connect
def _prewarm_deep_research_runtime(**_kwargs) -> None:
    async def _warm() -> None:
        cfg = get_settings()
        from app.worker.deep_research_runtime_cache import get_cached_runner
        from app.worker.task_resources import managed_task_resources

        async with managed_task_resources(settings=cfg, with_engine=True) as _resources:
            await get_cached_runner(settings=cfg)

    try:
        asyncio.run(_warm(), loop_factory=windows_selector_loop_factory)
    except Exception as exc:  # pragma: no cover - worker hook best effort
        logger.warning(
            "Deep research runtime prewarm failed",
            extra={"error": str(exc)},
            exc_info=True,
        )


@worker_process_shutdown.connect
def _shutdown_deep_research_runtime_cache(**_kwargs) -> None:
    async def _shutdown() -> None:
        from app.worker.deep_research_runtime_cache import DeepResearchRuntimeCache

        await DeepResearchRuntimeCache.shutdown()

    try:
        asyncio.run(_shutdown(), loop_factory=windows_selector_loop_factory)
    except Exception as exc:  # pragma: no cover - worker hook best effort
        logger.warning(
            "Deep research runtime cache shutdown failed",
            extra={"error": str(exc)},
            exc_info=True,
        )
