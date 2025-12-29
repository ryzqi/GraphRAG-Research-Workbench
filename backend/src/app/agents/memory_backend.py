"""DeepAgents 记忆后端构建器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore

from app.core.settings import Settings, get_settings


def _normalize_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        return "/memories/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return normalized


def _resolve_store_url(settings: Settings) -> str:
    url = settings.memory_store_url or settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql://")


def build_store(settings: Settings) -> BaseStore:
    backend = settings.memory_store_backend.strip().lower()
    if not settings.memory_enabled or backend == "memory":
        return InMemoryStore()
    if backend == "postgres":
        return PostgresStore(connection_string=_resolve_store_url(settings))
    raise ValueError(f"不支持的记忆后端类型: {settings.memory_store_backend}")


@dataclass(frozen=True)
class MemoryBackendFactory:
    """构建 DeepAgents 的记忆后端。"""

    store: BaseStore
    memory_path: str
    memory_enabled: bool

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None
    ) -> "MemoryBackendFactory":
        settings = settings or get_settings()
        return cls(
            store=build_store(settings),
            memory_path=_normalize_path(settings.memory_store_path),
            memory_enabled=settings.memory_enabled,
        )

    def build_backend(self) -> Callable[[object], CompositeBackend]:
        memory_path = self.memory_path
        memory_enabled = self.memory_enabled

        def _backend(runtime: object) -> CompositeBackend:
            state_backend = StateBackend(runtime)
            if not memory_enabled:
                return CompositeBackend(default=state_backend, routes={})
            return CompositeBackend(
                default=state_backend,
                routes={memory_path: StoreBackend(runtime)},
            )

        return _backend
