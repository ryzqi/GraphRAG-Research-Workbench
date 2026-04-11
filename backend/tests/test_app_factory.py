from __future__ import annotations

from fastapi import FastAPI

from app.bootstrap.app_factory import create_app
from app.core.middleware.request_id import RequestIdMiddleware
from app.core.settings import get_settings


def test_create_app_registers_routes_lifespan_and_request_id_middleware() -> None:
    app = create_app(get_settings())

    assert isinstance(app, FastAPI)
    route_paths = {getattr(route, 'path', '') for route in app.routes}
    assert '/api/v1/health' in route_paths
    assert app.router.lifespan_context is not None
    assert any(middleware.cls is RequestIdMiddleware for middleware in app.user_middleware)
