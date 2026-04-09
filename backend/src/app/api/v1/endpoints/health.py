from __future__ import annotations

import asyncio
import time

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import build_error_response
from app.core.logging import get_request_id
from app.integrations.milvus_client import MilvusClient
from app.integrations.object_storage import ObjectStorage
from app.integrations.redis_client import RedisClient

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


async def _check_postgres(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis(redis: RedisClient) -> None:
    await redis.ping()


async def _check_milvus(milvus: MilvusClient) -> None:
    await milvus.ready_check()


async def _check_minio() -> None:
    storage = ObjectStorage()

    def _check() -> None:
        storage._client.bucket_exists(storage._settings.minio_bucket_uploads)

    # 在线程 worker 中执行；abandon_on_cancel 可避免 SDK 阻塞时 readiness 卡住。
    await anyio.to_thread.run_sync(_check, abandon_on_cancel=True)


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness：短超时探测关键依赖，可降级返回。"""
    engine = request.app.state.engine
    redis = request.app.state.redis
    milvus = request.app.state.milvus_client
    tasks = {
        "postgres": asyncio.create_task(
            _timed("postgres", _check_postgres(engine), 1.0)
        ),
        "redis": asyncio.create_task(_timed("redis", _check_redis(redis), 0.8)),
        "milvus": asyncio.create_task(_timed("milvus", _check_milvus(milvus), 0.8)),
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
    return JSONResponse(
        status_code=200, content={"status": status, "dependencies": results}
    )
