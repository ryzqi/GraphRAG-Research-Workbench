from __future__ import annotations

from celery import Celery

from app.core.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "mkb_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.worker.tasks.export",
        "app.worker.tasks.ingestion",
        "app.worker.tasks.research",
        "app.worker.tasks.evaluation",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    timezone="Asia/Shanghai",
)
