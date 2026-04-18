from unittest.mock import MagicMock

import pytest

from app.core import checkpoint as checkpoint_module


@pytest.fixture(autouse=True)
def _reset() -> None:
    checkpoint_module.CheckpointManager._checkpointer = None
    checkpoint_module.CheckpointManager._initialized = False
    checkpoint_module.CheckpointManager._last_error = None
    if hasattr(checkpoint_module.CheckpointManager, "_checkpointer_ctx"):
        checkpoint_module.CheckpointManager._checkpointer_ctx = None
    yield
    checkpoint_module.CheckpointManager._checkpointer = None
    checkpoint_module.CheckpointManager._initialized = False
    checkpoint_module.CheckpointManager._last_error = None
    if hasattr(checkpoint_module.CheckpointManager, "_checkpointer_ctx"):
        checkpoint_module.CheckpointManager._checkpointer_ctx = None


async def test_initialize_uses_shared_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = MagicMock(name="pool")
    monkeypatch.setattr(
        checkpoint_module.LangGraphPostgresPool,
        "get_pool",
        classmethod(lambda cls: fake_pool),
    )
    monkeypatch.setattr(
        checkpoint_module.LangGraphPostgresPool,
        "_initialized",
        True,
    )

    setup_calls: list[str] = []

    class _Saver:
        def __init__(self, conn: object) -> None:
            self.conn = conn

        async def setup(self) -> None:
            setup_calls.append("setup")

    monkeypatch.setattr(checkpoint_module, "AsyncPostgresSaver", _Saver)

    await checkpoint_module.CheckpointManager.initialize()
    checkpointer = checkpoint_module.CheckpointManager.get_checkpointer()

    assert checkpointer.conn is fake_pool
    assert setup_calls == ["setup"]


async def test_initialize_requires_pool_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        checkpoint_module.LangGraphPostgresPool,
        "_initialized",
        False,
    )

    with pytest.raises(RuntimeError, match="pool"):
        await checkpoint_module.CheckpointManager.initialize()
