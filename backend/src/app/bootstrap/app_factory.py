from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.bootstrap.lifespan import create_lifespan
from app.core.errors import register_exception_handlers
from app.core.middleware.request_id import RequestIdMiddleware
from app.core.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=create_lifespan(settings),
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app_cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "Last-Event-ID"],
    )

    app.include_router(api_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app
