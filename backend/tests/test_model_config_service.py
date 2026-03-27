from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import AppError
from app.core.settings import get_settings
from app.models.model_config import (
    ModelProvider as ModelProviderORM,
    ModelProviderConfig,
    ModelRuntimeSelection,
)
from app.schemas.model_config import (
    ActiveModelUpdate,
    ModelProvider,
    ProviderConfigUpdate,
)
from app.services.model_config_service import ModelConfigService


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class _FakeSession:
    def __init__(
        self,
        *,
        provider_rows: list[ModelProviderConfig],
        selection: ModelRuntimeSelection,
    ) -> None:
        self.provider_rows = {row.provider: row for row in provider_rows}
        self.selection = selection
        self.commit_calls = 0
        self.refresh_calls: list[tuple[object, tuple[str, ...] | None]] = []

    async def get(self, model: object, pk: object) -> object | None:
        if model is ModelProviderConfig:
            return self.provider_rows.get(pk)
        if model is ModelRuntimeSelection and pk == 1:
            return self.selection
        raise AssertionError(f"Unexpected get({model!r}, {pk!r})")

    async def execute(self, _statement: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(list(self.provider_rows.values()))

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(
        self, obj: object, attribute_names: list[str] | None = None
    ) -> None:
        self.refresh_calls.append(
            (obj, tuple(attribute_names) if attribute_names is not None else None)
        )


def _build_provider_row(
    provider: ModelProviderORM,
    *,
    enabled: bool = True,
    base_url: str | None = None,
    models: list[str] | None = None,
    thinking_enabled: bool = True,
    thinking_level: str | None = None,
) -> ModelProviderConfig:
    return ModelProviderConfig(
        provider=provider,
        enabled=enabled,
        base_url=base_url,
        api_key_encrypted=None,
        models=list(models or []),
        thinking_enabled=thinking_enabled,
        thinking_level=thinking_level,
    )


def _build_service(db: _FakeSession) -> ModelConfigService:
    return ModelConfigService(db=db, settings=get_settings())


@pytest.mark.asyncio
async def test_set_active_model_probes_target_before_commit(monkeypatch) -> None:
    target_model = "minimaxai/minimax-m2.5"
    db = _FakeSession(
        provider_rows=[
            _build_provider_row(
                ModelProviderORM.NVIDIA,
                base_url="https://integrate.api.nvidia.com/v1",
                models=[target_model],
            )
        ],
        selection=ModelRuntimeSelection(
            id=1,
            active_provider=ModelProviderORM.OPENAI,
            active_model="gpt-4o-mini",
        ),
    )
    service = _build_service(db)
    probe_calls: list[tuple[Any, str]] = []
    expected = object()

    async def _noop() -> None:
        return None

    async def _fake_probe(*, provider_cfg: Any, model_name: str) -> None:
        probe_calls.append((provider_cfg, model_name))

    async def _fake_get_config() -> object:
        return expected

    monkeypatch.setattr(service, "_ensure_defaults", _noop)
    monkeypatch.setattr(service, "_probe_runtime_target", _fake_probe)
    monkeypatch.setattr(service, "get_config", _fake_get_config)

    result = await service.set_active_model(
        ActiveModelUpdate(provider=ModelProvider.NVIDIA, model=target_model)
    )

    assert result is expected
    assert db.commit_calls == 1
    assert db.selection.active_provider == ModelProviderORM.NVIDIA
    assert db.selection.active_model == target_model
    assert len(probe_calls) == 1
    assert probe_calls[0][0].provider == ModelProviderORM.NVIDIA
    assert probe_calls[0][1] == target_model


@pytest.mark.asyncio
async def test_set_active_model_probe_failure_prevents_commit(monkeypatch) -> None:
    db = _FakeSession(
        provider_rows=[
            _build_provider_row(
                ModelProviderORM.NVIDIA,
                base_url="https://integrate.api.nvidia.com/v1",
                models=["minimaxai/minimax-m2.5"],
            )
        ],
        selection=ModelRuntimeSelection(
            id=1,
            active_provider=ModelProviderORM.OPENAI,
            active_model="gpt-4o-mini",
        ),
    )
    service = _build_service(db)

    async def _noop() -> None:
        return None

    async def _fake_probe(*, provider_cfg: Any, model_name: str) -> None:
        raise AppError(
            code="MODEL_PROBE_TIMEOUT",
            message=f"模型健康检查超时: {provider_cfg.provider.value}/{model_name}",
            status_code=504,
        )

    monkeypatch.setattr(service, "_ensure_defaults", _noop)
    monkeypatch.setattr(service, "_probe_runtime_target", _fake_probe)

    with pytest.raises(AppError, match="模型健康检查超时"):
        await service.set_active_model(
            ActiveModelUpdate(
                provider=ModelProvider.NVIDIA,
                model="minimaxai/minimax-m2.5",
            )
        )

    assert db.commit_calls == 0
    assert db.selection.active_provider == ModelProviderORM.OPENAI
    assert db.selection.active_model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_update_provider_probes_active_runtime_config_before_commit(
    monkeypatch,
) -> None:
    active_model = "minimaxai/minimax-m2.5"
    db = _FakeSession(
        provider_rows=[
            _build_provider_row(
                ModelProviderORM.NVIDIA,
                base_url="https://integrate.api.nvidia.com/v1",
                models=[active_model],
                thinking_enabled=True,
            )
        ],
        selection=ModelRuntimeSelection(
            id=1,
            active_provider=ModelProviderORM.NVIDIA,
            active_model=active_model,
        ),
    )
    service = _build_service(db)
    probe_calls: list[tuple[Any, str]] = []
    expected = object()

    async def _noop() -> None:
        return None

    async def _fake_probe(*, provider_cfg: Any, model_name: str) -> None:
        probe_calls.append((provider_cfg, model_name))

    async def _fake_get_config() -> object:
        return expected

    monkeypatch.setattr(service, "_ensure_defaults", _noop)
    monkeypatch.setattr(service, "_probe_runtime_target", _fake_probe)
    monkeypatch.setattr(service, "get_config", _fake_get_config)

    result = await service.update_provider(
        provider=ModelProvider.NVIDIA,
        payload=ProviderConfigUpdate(thinking_enabled=False),
    )

    assert result is expected
    assert db.commit_calls == 1
    assert db.selection.active_provider == ModelProviderORM.NVIDIA
    assert db.selection.active_model == active_model
    assert len(probe_calls) == 1
    assert probe_calls[0][0].thinking_enabled is False
    assert probe_calls[0][1] == active_model


@pytest.mark.asyncio
async def test_update_provider_probe_failure_preserves_current_selection(
    monkeypatch,
) -> None:
    fallback_model = "gpt-4o-mini"
    db = _FakeSession(
        provider_rows=[
            _build_provider_row(
                ModelProviderORM.OPENAI,
                base_url="https://api.openai.com/v1",
                models=[fallback_model],
                thinking_level="high",
            ),
            _build_provider_row(
                ModelProviderORM.NVIDIA,
                base_url="https://integrate.api.nvidia.com/v1",
                models=["minimaxai/minimax-m2.5"],
            ),
        ],
        selection=ModelRuntimeSelection(
            id=1,
            active_provider=ModelProviderORM.NVIDIA,
            active_model="minimaxai/minimax-m2.5",
        ),
    )
    service = _build_service(db)

    async def _noop() -> None:
        return None

    async def _fake_probe(*, provider_cfg: Any, model_name: str) -> None:
        raise AppError(
            code="MODEL_PROBE_TIMEOUT",
            message=f"模型健康检查超时: {provider_cfg.provider.value}/{model_name}",
            status_code=504,
        )

    monkeypatch.setattr(service, "_ensure_defaults", _noop)
    monkeypatch.setattr(service, "_probe_runtime_target", _fake_probe)

    with pytest.raises(AppError, match=fallback_model):
        await service.update_provider(
            provider=ModelProvider.NVIDIA,
            payload=ProviderConfigUpdate(enabled=False),
        )

    assert db.commit_calls == 0
    assert db.selection.active_provider == ModelProviderORM.NVIDIA
    assert db.selection.active_model == "minimaxai/minimax-m2.5"
