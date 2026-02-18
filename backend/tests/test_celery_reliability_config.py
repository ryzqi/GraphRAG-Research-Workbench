from __future__ import annotations

from app.worker.celery_app import celery_app


def test_celery_reliability_and_event_settings() -> None:
    conf = celery_app.conf

    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_acks_on_failure_or_timeout is True
    assert conf.worker_send_task_events is True
    assert conf.task_send_sent_event is True
    assert conf.broker_transport_options["visibility_timeout"] == 7200


def test_celery_queue_routes_and_beat_schedule() -> None:
    conf = celery_app.conf

    queue_names = {queue.name for queue in conf.task_queues}
    assert {"default", "dispatch", "ingestion", "rebuild", "research", "export"}.issubset(
        queue_names
    )

    routes = conf.task_routes
    assert routes["app.worker.tasks.ingestion_outbox_dispatcher.dispatch_ingestion_outbox"]["queue"] == "dispatch"
    assert routes["app.worker.tasks.index_rebuild_outbox_dispatcher.dispatch_index_rebuild_outbox"]["queue"] == "dispatch"
    assert routes["app.worker.tasks.ingestion_batches.run_ingestion_batch_doc"]["queue"] == "ingestion"
    assert routes["app.worker.tasks.index_rebuild.run_index_rebuild_job"]["queue"] == "rebuild"

    beat_schedule = conf.beat_schedule
    assert "ingestion-outbox-dispatcher" in beat_schedule
    assert "index-rebuild-outbox-dispatcher" in beat_schedule
