from __future__ import annotations

from app.core.settings import Settings
from app.worker.celery_app import celery_app


def test_settings_celery_runtime_defaults() -> None:
    settings = Settings(APP_ENV="test")

    assert settings.celery_worker_send_task_events is False
    assert settings.celery_task_send_sent_event is False
    assert settings.celery_worker_prefetch_multiplier == 1
    assert settings.celery_task_store_errors_even_if_ignored is True
    assert settings.celery_task_soft_time_limit_seconds == 0
    assert settings.celery_task_time_limit_seconds == 0


def test_celery_app_runtime_defaults_are_low_overhead() -> None:
    assert celery_app.conf.worker_send_task_events is False
    assert celery_app.conf.task_send_sent_event is False
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_store_errors_even_if_ignored is True


def test_celery_app_disables_global_time_limits_by_default() -> None:
    assert celery_app.conf.task_soft_time_limit in (None, 0)
    assert celery_app.conf.task_time_limit in (None, 0)
