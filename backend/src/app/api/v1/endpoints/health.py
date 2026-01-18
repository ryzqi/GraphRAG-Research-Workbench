from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.errors import build_error_response
from app.core.logging import get_request_id
from app.db.session import get_engine
from app.integrations.milvus_client import get_milvus_client
from app.integrations.object_storage import ObjectStorage
from app.integrations.redis_client import get_redis

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _timed(name: str, coro, timeout_seconds: float) -> dict[str, object]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=timeout_seconds)
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "error": None,
    }


async def _check_postgres() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    redis = get_redis()
    await redis.ping()


async def _check_milvus() -> None:
    milvus = get_milvus_client()
    await milvus.ready_check()


async def _check_minio() -> None:
    storage = ObjectStorage()

    def _check() -> None:
        storage._client.bucket_exists(storage._settings.minio_bucket_uploads)

    await asyncio.to_thread(_check)


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness：短超时探测关键依赖，可降级返回。"""
    tasks = {
        "postgres": asyncio.create_task(_timed("postgres", _check_postgres(), 1.0)),
        "redis": asyncio.create_task(_timed("redis", _check_redis(), 0.8)),
        "milvus": asyncio.create_task(_timed("milvus", _check_milvus(), 0.8)),
        "minio": asyncio.create_task(_timed("minio", _check_minio(), 0.8)),
    }

    results = {name: await task for name, task in tasks.items()}
    postgres_ok = bool(results.get("postgres", {}).get("ok"))

    if not postgres_ok:
        return JSONResponse(
            status_code=503,
            content=build_error_response(
                code="NOT_READY",
                message="服务未就绪",
                request_id=get_request_id(),
                details={"dependencies": results},
            ),
        )

    degraded = any(not bool(r.get("ok")) for k, r in results.items() if k != "postgres")
    status = "degraded" if degraded else "ready"
    return JSONResponse(status_code=200, content={"status": status, "dependencies": results})
