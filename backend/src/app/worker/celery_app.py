from __future__ import annotations

from datetime import timedelta

from celery import Celery
from kombu import Queue

from app.core.settings import get_settings

settings = get_settings()

DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 7_200
DEFAULT_DISPATCH_BATCH_SIZE = 50

celery_app = Celery(
    "mkb_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.worker.tasks.export",
        "app.worker.tasks.ingestion_batches",
        "app.worker.tasks.ingestion_outbox_dispatcher",
        "app.worker.tasks.index_rebuild",
        "app.worker.tasks.index_rebuild_outbox_dispatcher",
        "app.worker.tasks.kb_bootstrap_jobs",
        "app.worker.tasks.research",
    ],
)

celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": DEFAULT_VISIBILITY_TIMEOUT_SECONDS},
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    result_accept_content=["json"],
    task_ignore_result=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("dispatch"),
        Queue("ingestion"),
        Queue("rebuild"),
        Queue("research"),
        Queue("export"),
    ),
    task_routes={
        "app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox": {
            "queue": "dispatch"
        },
        "app.worker.tasks.index_rebuild_outbox_dispatcher.dispatch_index_rebuild_outbox": {
            "queue": "dispatch"
        },
        "app.worker.tasks.ingestion_batches.run_ingestion_batch_doc": {
            "queue": "ingestion"
        },
        "app.worker.tasks.index_rebuild.run_index_rebuild_job": {"queue": "rebuild"},
        "app.worker.tasks.research.run_research": {"queue": "research"},
        "app.worker.tasks.research.run_research_v2": {"queue": "research"},
        "app.worker.tasks.export.run_export": {"queue": "export"},
        "app.worker.tasks.kb_bootstrap_jobs.run_kb_bootstrap_job": {
            "queue": "default"
        },
    },
    timezone="Asia/Shanghai",
    task_soft_time_limit=60 * 60,
    task_time_limit=65 * 60,
    beat_schedule={
        "ingestion-outbox-dispatcher": {
            "task": "app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox",
            "schedule": timedelta(seconds=15),
            "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
        },
        "index-rebuild-outbox-dispatcher": {
            "task": "app.worker.tasks.index_rebuild_outbox_dispatcher.dispatch_index_rebuild_outbox",
            "schedule": timedelta(seconds=15),
            "kwargs": {"limit": DEFAULT_DISPATCH_BATCH_SIZE},
        }
    },
)
