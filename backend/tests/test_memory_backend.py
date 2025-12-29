from langgraph.store.memory import InMemoryStore

from app.agents.memory_backend import _normalize_path, build_store
from app.core.settings import Settings


def test_normalize_path() -> None:
    assert _normalize_path("memories") == "/memories/"
    assert _normalize_path("/memories") == "/memories/"
    assert _normalize_path("/memories/") == "/memories/"


def test_build_store_memory_backend() -> None:
    settings = Settings(memory_enabled=True, memory_store_backend="memory")
    store = build_store(settings)
    assert isinstance(store, InMemoryStore)
