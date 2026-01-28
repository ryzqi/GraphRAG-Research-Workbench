from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.settings import Settings, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    cfg = get_settings()
    return create_async_engine(
        cfg.database_url,
        pool_pre_ping=True,
        pool_size=cfg.db_pool_size,
        max_overflow=cfg.db_max_overflow,
        pool_recycle=cfg.db_pool_recycle_seconds,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


def create_engine(
    settings: Settings | None = None,
    *,
    use_null_pool: bool = False,
) -> AsyncEngine:
    cfg = settings or get_settings()
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": cfg.db_pool_size,
        "max_overflow": cfg.db_max_overflow,
        "pool_recycle": cfg.db_pool_recycle_seconds,
    }
    if use_null_pool:
        engine_kwargs["poolclass"] = NullPool
    return create_async_engine(cfg.database_url, **engine_kwargs)


def create_sessionmaker(
    engine: AsyncEngine | None = None,
    settings: Settings | None = None,
) -> async_sessionmaker[AsyncSession]:
    base_engine = engine or create_engine(settings)
    return async_sessionmaker(base_engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session
