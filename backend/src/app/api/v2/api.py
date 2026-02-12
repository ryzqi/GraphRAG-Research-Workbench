from __future__ import annotations

from fastapi import APIRouter

from app.api.v2.endpoints import research

api_router_v2 = APIRouter()
api_router_v2.include_router(research.router, prefix="/research", tags=["ResearchV2"])

