"""模型配置服务。"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.secrets import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    resolve_model_config_kms_key,
)
from app.core.settings import Settings, get_settings
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.model_config import (
    ModelProvider as ModelProviderORM,
    ModelProviderConfig,
    ModelRuntimeSelection,
)
from app.schemas.model_config import (
    ActiveModelUpdate,
    ModelConfigRead,
    ModelProvider,
    ProviderConfigRead,
    ProviderConfigUpdate,
)

_PROVIDER_ORDER = [
    ModelProviderORM.OPENAI,
    ModelProviderORM.OLLAMA,
    ModelProviderORM.NVIDIA,
]


def _as_schema_provider(provider: ModelProviderORM) -> ModelProvider:
    return ModelProvider(provider.value)


def _as_model_provider(provider: ModelProvider) -> ModelProviderORM:
    return ModelProviderORM(provider.value)


def _default_base_url(provider: ModelProviderORM, settings: Settings) -> str | None:
    if provider == ModelProviderORM.OPENAI:
        return settings.llm_base_url.rstrip("/")
    if provider == ModelProviderORM.OLLAMA:
        return "http://127.0.0.1:11434"
    return None


def _default_thinking_level(provider: ModelProviderORM) -> str | None:
    if provider in {ModelProviderORM.OPENAI, ModelProviderORM.OLLAMA}:
        return "high"
    return None


def _default_model(provider: ModelProviderORM, settings: Settings) -> str | None:
    if provider == ModelProviderORM.OPENAI:
        return settings.llm_model.strip() or None
    return None


class ModelConfigService:
    def __init__(self, db: AsyncSession, *, settings: Settings | None = None) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._kms_key = resolve_model_config_kms_key(self._settings)

    async def get_config(self) -> ModelConfigRead:
        await self._ensure_defaults()
        provider_rows = await self._list_provider_rows()
        selection = await self._get_selection()
        return self._to_config_read(provider_rows=provider_rows, selection=selection)

    async def update_provider(
        self,
        *,
        provider: ModelProvider,
        payload: ProviderConfigUpdate,
    ) -> ModelConfigRead:
        await self._ensure_defaults()
        provider_orm = _as_model_provider(provider)
        row = await self._db.get(ModelProviderConfig, provider_orm)
        if row is None:
            raise AppError(
                code="MODEL_PROVIDER_NOT_FOUND",
                message=f"模型供应商不存在: {provider.value}",
                status_code=404,
            )

        updates = payload.model_dump(exclude_unset=True)
        if "enabled" in updates:
            row.enabled = bool(updates["enabled"])
        if "base_url" in updates:
            row.base_url = updates["base_url"]
        if "model" in updates:
            row.model = updates["model"]
        if "thinking_enabled" in updates:
            row.thinking_enabled = bool(updates["thinking_enabled"])
        if "thinking_level" in updates:
            if row.provider == ModelProviderORM.NVIDIA:
                row.thinking_level = None
            else:
                row.thinking_level = updates["thinking_level"] or "high"
        if "api_key" in updates:
            api_key_raw = (updates["api_key"] or "").strip()
            row.api_key_encrypted = (
                encrypt_secret(api_key_raw, kms_key=self._kms_key)
                if api_key_raw
                else None
            )

        selection = await self._get_selection()
        if selection.active_provider == row.provider:
            selection.active_model = row.model

        await self._db.commit()
        await ModelRuntimeConfigManager.refresh(db=self._db, settings=self._settings)
        return await self.get_config()

    async def set_active_model(self, payload: ActiveModelUpdate) -> ModelConfigRead:
        await self._ensure_defaults()
        provider_orm = _as_model_provider(payload.provider)
        row = await self._db.get(ModelProviderConfig, provider_orm)
        if row is None:
            raise AppError(
                code="MODEL_PROVIDER_NOT_FOUND",
                message=f"模型供应商不存在: {payload.provider.value}",
                status_code=404,
            )
        if not row.enabled:
            raise AppError(
                code="MODEL_PROVIDER_DISABLED",
                message=f"模型供应商未启用: {payload.provider.value}",
                status_code=422,
            )

        selected_model = (payload.model or row.model or "").strip()
        if not selected_model:
            raise AppError(
                code="MODEL_NOT_CONFIGURED",
                message="请先为该供应商配置可用模型名",
                status_code=422,
            )

        row.model = selected_model
        selection = await self._get_selection()
        selection.active_provider = row.provider
        selection.active_model = selected_model

        await self._db.commit()
        await ModelRuntimeConfigManager.refresh(db=self._db, settings=self._settings)
        return await self.get_config()

    async def _ensure_defaults(self) -> None:
        provider_rows = await self._list_provider_rows()
        by_provider = {row.provider: row for row in provider_rows}
        dirty = False

        for provider in _PROVIDER_ORDER:
            if provider in by_provider:
                continue
            api_key_encrypted = None
            if provider == ModelProviderORM.OPENAI:
                raw_key = self._settings.llm_api_key.strip()
                if raw_key and raw_key != "REPLACE_ME":
                    api_key_encrypted = encrypt_secret(raw_key, kms_key=self._kms_key)
            row = ModelProviderConfig(
                provider=provider,
                enabled=True,
                base_url=_default_base_url(provider, self._settings),
                api_key_encrypted=api_key_encrypted,
                model=_default_model(provider, self._settings),
                thinking_enabled=True,
                thinking_level=_default_thinking_level(provider),
            )
            self._db.add(row)
            by_provider[provider] = row
            dirty = True

        selection = await self._db.get(ModelRuntimeSelection, 1)
        if selection is None:
            openai_row = by_provider[ModelProviderORM.OPENAI]
            selection = ModelRuntimeSelection(
                id=1,
                active_provider=ModelProviderORM.OPENAI,
                active_model=openai_row.model or self._settings.llm_model.strip() or None,
            )
            self._db.add(selection)
            dirty = True

        if dirty:
            await self._db.commit()

    async def _list_provider_rows(self) -> list[ModelProviderConfig]:
        result = await self._db.execute(select(ModelProviderConfig))
        return list(result.scalars().all())

    async def _get_selection(self) -> ModelRuntimeSelection:
        selection = await self._db.get(ModelRuntimeSelection, 1)
        if selection is None:
            # `_ensure_defaults` should always create it, this is a safe fallback.
            selection = ModelRuntimeSelection(
                id=1,
                active_provider=ModelProviderORM.OPENAI,
                active_model=self._settings.llm_model.strip() or None,
            )
            self._db.add(selection)
            await self._db.commit()
        return selection

    def _to_config_read(
        self,
        *,
        provider_rows: Iterable[ModelProviderConfig],
        selection: ModelRuntimeSelection,
    ) -> ModelConfigRead:
        rows = {row.provider: row for row in provider_rows}
        providers: list[ProviderConfigRead] = []
        for provider in _PROVIDER_ORDER:
            row = rows.get(provider)
            if row is None:
                continue
            api_key_set = bool(row.api_key_encrypted and row.api_key_encrypted.strip())
            api_key_masked = None
            if api_key_set:
                try:
                    api_key_plain = decrypt_secret(
                        row.api_key_encrypted or "",
                        kms_key=self._kms_key,
                    )
                except Exception:
                    api_key_plain = "***"
                api_key_masked = mask_secret(api_key_plain) or "******"

            providers.append(
                ProviderConfigRead(
                    provider=_as_schema_provider(row.provider),
                    enabled=row.enabled,
                    base_url=row.base_url,
                    model=row.model,
                    thinking_enabled=row.thinking_enabled,
                    thinking_level=row.thinking_level,
                    api_key_set=api_key_set,
                    api_key_masked=api_key_masked,
                    updated_at=row.updated_at,
                )
            )

        return ModelConfigRead(
            providers=providers,
            active_provider=_as_schema_provider(selection.active_provider),
            active_model=selection.active_model,
            updated_at=selection.updated_at,
        )
