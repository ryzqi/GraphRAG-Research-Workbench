from __future__ import annotations

from datetime import timedelta

from celery import Celery

from app.core.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "mkb_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.worker.tasks.export",
        "app.worker.tasks.ingestion_batches",
        "app.worker.tasks.ingestion_outbox_dispatcher",
        "app.worker.tasks.index_rebuild",
        "app.worker.tasks.kb_bootstrap_jobs",
        "app.worker.tasks.research",
        "app.worker.tasks.evaluation",
    ],
)

celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    result_accept_content=["json"],
    task_ignore_result=True,
    task_track_started=True,
    timezone="Asia/Shanghai",
    task_soft_time_limit=60 * 60,
    task_time_limit=65 * 60,
    beat_schedule={
        "ingestion-outbox-dispatcher": {
            "task": "app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox",
            "schedule": timedelta(seconds=15),
            "kwargs": {"limit": 50},
        }
    },
)
