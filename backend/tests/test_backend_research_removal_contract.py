from __future__ import annotations

from app.api.v1.api import api_router
from app.api.v2.api import api_router_v2
from app.models.agent_run import AgentRunType
from app.schemas.exports import ExportType
from app.worker.celery_app import celery_app


def _route_paths(router) -> set[str]:
    return {route.path for route in router.routes}


def test_research_routes_removed_from_api_routers() -> None:
    v1_paths = _route_paths(api_router)
    v2_paths = _route_paths(api_router_v2)

    assert "/research/runs" not in v1_paths
    assert not any(path.startswith("/research/") for path in v2_paths)


def test_research_removed_from_backend_public_types() -> None:
    assert "research" not in {item.value for item in AgentRunType}
    assert "research" not in {item.value for item in ExportType}


def test_research_tasks_removed_from_celery_registration() -> None:
    include_modules = set(celery_app.conf.include or [])
    task_routes = dict(celery_app.conf.task_routes or {})
    queue_names = {queue.name for queue in celery_app.conf.task_queues or ()}

    assert "app.worker.tasks.research" not in include_modules
    assert "app.worker.tasks.research.run_research" not in task_routes
    assert "app.worker.tasks.research.run_research_v2" not in task_routes
    assert "research" not in queue_names
