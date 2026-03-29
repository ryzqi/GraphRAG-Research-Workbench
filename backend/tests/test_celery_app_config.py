from __future__ import annotations

from app.worker.celery_app import celery_app


def test_research_task_routes_to_research_queue() -> None:
    queue_names = {queue.name for queue in celery_app.conf.task_queues}

    assert "research" in queue_names
    assert (
        celery_app.conf.task_routes["app.worker.tasks.research.run_research_session"]["queue"]
        == "research"
    )
