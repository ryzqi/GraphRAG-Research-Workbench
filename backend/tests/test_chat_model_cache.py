from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.settings import Settings
from app.integrations import chat_model_cache as cache_module
from app.integrations import model_runtime_config as runtime_module
from app.models.model_config import ModelProvider


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def _provider_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        provider=ModelProvider.OPENAI,
        api_key="sk-xxx",
        base_url="https://api.example.com",
        enabled=True,
        thinking_enabled=False,
        thinking_level=None,
        models=["gpt-4o"],
    )


@pytest.fixture(autouse=True)
def _clear_chat_model_cache() -> None:
    cache_module.ChatModelCache.clear()
    yield
    cache_module.ChatModelCache.clear()


def test_cache_reuses_model_with_same_fingerprint(monkeypatch) -> None:
    settings = _make_settings()
    call_count = 0
    sentinel = MagicMock(name="chat_model")

    def _fake_factory(**_kwargs):
        nonlocal call_count
        call_count += 1
        return sentinel

    monkeypatch.setattr(
        cache_module,
        "create_chat_model_from_runtime_config",
        _fake_factory,
    )

    class _FakeSnapshot:
        active_model = "gpt-4o"
        version = 1

        def active_provider_config(self):
            return _provider_cfg()

    monkeypatch.setattr(
        cache_module.ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(lambda cls, settings=None: _FakeSnapshot()),
    )

    m1 = cache_module.create_chat_model_cached(settings=settings)
    m2 = cache_module.create_chat_model_cached(settings=settings)

    assert m1 is sentinel
    assert m2 is sentinel
    assert call_count == 1


def test_cache_invalidates_on_snapshot_version_change(monkeypatch) -> None:
    settings = _make_settings()
    built: list[MagicMock] = []

    def _fake_factory(**_kwargs):
        model = MagicMock(name=f"model_{len(built)}")
        built.append(model)
        return model

    monkeypatch.setattr(
        cache_module,
        "create_chat_model_from_runtime_config",
        _fake_factory,
    )

    versions = iter([1, 1, 2])

    class _FakeSnapshot:
        active_model = "gpt-4o"

        def __init__(self, version: int) -> None:
            self.version = version

        def active_provider_config(self):
            return _provider_cfg()

    monkeypatch.setattr(
        cache_module.ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(lambda cls, settings=None: _FakeSnapshot(next(versions))),
    )

    first = cache_module.create_chat_model_cached(settings=settings)
    second = cache_module.create_chat_model_cached(settings=settings)
    third = cache_module.create_chat_model_cached(settings=settings)

    assert first is second
    assert third is not first
    assert len(built) == 2


def test_cache_keys_on_use_previous_response_id(monkeypatch) -> None:
    settings = _make_settings()
    built: list[bool | None] = []

    def _fake_factory(*, use_previous_response_id, **_kwargs):
        built.append(use_previous_response_id)
        return MagicMock(name=f"model_{use_previous_response_id}")

    monkeypatch.setattr(
        cache_module,
        "create_chat_model_from_runtime_config",
        _fake_factory,
    )

    class _FakeSnapshot:
        active_model = "gpt-4o"
        version = 1

        def active_provider_config(self):
            return _provider_cfg()

    monkeypatch.setattr(
        cache_module.ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(lambda cls, settings=None: _FakeSnapshot()),
    )

    cache_module.create_chat_model_cached(
        settings=settings,
        use_previous_response_id=None,
    )
    cache_module.create_chat_model_cached(
        settings=settings,
        use_previous_response_id=False,
    )
    cache_module.create_chat_model_cached(
        settings=settings,
        use_previous_response_id=True,
    )
    cache_module.create_chat_model_cached(
        settings=settings,
        use_previous_response_id=None,
    )

    assert built == [None, False, True]


async def test_model_runtime_snapshot_version_increments_on_refresh(monkeypatch) -> None:
    settings = _make_settings()

    class _SessionScope:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    class _Sessionmaker:
        def __call__(self) -> _SessionScope:
            return _SessionScope()

    async def _fake_load_snapshot(_cls, *, db, settings):
        provider_cfg = runtime_module.RuntimeProviderConfig(
            provider=ModelProvider.OPENAI,
            enabled=True,
            base_url="https://api.example.com",
            api_key="sk-xxx",
            models=["gpt-4o"],
            thinking_enabled=False,
            thinking_level=None,
        )
        return runtime_module.RuntimeModelSnapshot(
            providers={ModelProvider.OPENAI: provider_cfg},
            active_provider=ModelProvider.OPENAI,
            active_model="gpt-4o",
            updated_at=None,
            version=0,
        )

    monkeypatch.setattr(
        runtime_module.ModelRuntimeConfigManager,
        "_load_snapshot",
        classmethod(_fake_load_snapshot),
    )
    monkeypatch.setattr(runtime_module.ModelRuntimeConfigManager, "_snapshot", None)
    monkeypatch.setattr(runtime_module.ModelRuntimeConfigManager, "_initialized", False)
    monkeypatch.setattr(runtime_module.ModelRuntimeConfigManager, "_sessionmaker", _Sessionmaker())
    monkeypatch.setattr(runtime_module.ModelRuntimeConfigManager, "_lock", None)
    monkeypatch.setattr(runtime_module.ModelRuntimeConfigManager, "_lock_loop", None)
    monkeypatch.setattr(
        runtime_module.ModelRuntimeConfigManager,
        "_version",
        0,
        raising=False,
    )

    await runtime_module.ModelRuntimeConfigManager.refresh(settings=settings)
    first = runtime_module.ModelRuntimeConfigManager.get_snapshot(settings=settings)

    await runtime_module.ModelRuntimeConfigManager.refresh(settings=settings)
    second = runtime_module.ModelRuntimeConfigManager.get_snapshot(settings=settings)

    assert first.version == 1
    assert second.version == 2
