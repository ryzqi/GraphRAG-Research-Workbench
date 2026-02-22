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


def _normalize_model_names(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _provider_candidates_after(
    provider: ModelProviderORM,
) -> list[ModelProviderORM]:
    try:
        idx = _PROVIDER_ORDER.index(provider)
    except ValueError:
        return list(_PROVIDER_ORDER)
    return [*_PROVIDER_ORDER[idx + 1 :], *_PROVIDER_ORDER[:idx]]


def _pick_next_enabled_provider(
    *,
    by_provider: dict[ModelProviderORM, ModelProviderConfig],
    current_provider: ModelProviderORM,
) -> ModelProviderConfig | None:
    candidates = _provider_candidates_after(current_provider)
    for candidate in candidates:
        row = by_provider.get(candidate)
        if row is not None and row.enabled and _normalize_model_names(row.models):
            return row

    for candidate in candidates:
        row = by_provider.get(candidate)
        if row is not None and row.enabled:
            return row
    return None


def _as_schema_provider(provider: ModelProviderORM) -> ModelProvider:
    return ModelProvider(provider.value)


def _as_model_provider(provider: ModelProvider) -> ModelProviderORM:
    return ModelProviderORM(provider.value)


def _default_base_url(_provider: ModelProviderORM) -> str | None:
    return None


def _default_thinking_level(provider: ModelProviderORM) -> str | None:
    if provider in {ModelProviderORM.OPENAI, ModelProviderORM.OLLAMA}:
        return "high"
    return None


def _default_models(_provider: ModelProviderORM) -> list[str]:
    return []


class ModelConfigService:
    def __init__(self, db: AsyncSession, *, settings: Settings | None = None) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._kms_key = resolve_model_config_kms_key(self._settings)

    async def get_config(self) -> ModelConfigRead:
        await self._ensure_defaults()
        # Keep in-memory runtime snapshot aligned with latest DB config
        # even when users only visit/read the model-config page.
        await ModelRuntimeConfigManager.refresh(db=self._db, settings=self._settings)
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
        if "models" in updates:
            row.models = _normalize_model_names(updates["models"])
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
        if (
            "enabled" in updates
            and not row.enabled
            and selection.active_provider == row.provider
        ):
            provider_rows = await self._list_provider_rows()
            by_provider = {item.provider: item for item in provider_rows}
            next_provider = _pick_next_enabled_provider(
                by_provider=by_provider,
                current_provider=row.provider,
            )
            if next_provider is None:
                raise AppError(
                    code="NO_ENABLED_MODEL_PROVIDER",
                    message="至少保留一个启用的模型供应商",
                    status_code=422,
                )
            next_model = self._resolve_active_model(next_provider)
            if not next_model:
                raise AppError(
                    code="NO_ENABLED_MODEL_PROVIDER",
                    message="无可切换的已启用供应商（缺少模型名）",
                    status_code=422,
                )
            selection.active_provider = next_provider.provider
            selection.active_model = next_model
        elif selection.active_provider == row.provider:
            available_models = _normalize_model_names(row.models)
            active_model = (selection.active_model or "").strip()
            if active_model and active_model in available_models:
                selection.active_model = active_model
            else:
                next_model = self._resolve_active_model(row)
                if next_model:
                    selection.active_model = next_model
                else:
                    provider_rows = await self._list_provider_rows()
                    by_provider = {item.provider: item for item in provider_rows}
                    next_provider = _pick_next_enabled_provider(
                        by_provider=by_provider,
                        current_provider=row.provider,
                    )
                    if next_provider is None:
                        raise AppError(
                            code="NO_ENABLED_MODEL_PROVIDER",
                            message="至少保留一个启用的模型供应商",
                            status_code=422,
                        )
                    next_provider_model = self._resolve_active_model(next_provider)
                    if not next_provider_model:
                        raise AppError(
                            code="NO_ENABLED_MODEL_PROVIDER",
                            message="无可切换的已启用供应商（缺少模型名）",
                            status_code=422,
                        )
                    selection.active_provider = next_provider.provider
                    selection.active_model = next_provider_model

        await self._db.commit()
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

        provider_models = _normalize_model_names(row.models)
        requested_model = (payload.model or "").strip()
        if requested_model and requested_model not in provider_models:
            raise AppError(
                code="MODEL_NOT_CONFIGURED",
                message="请从该供应商已配置模型中选择",
                status_code=422,
            )

        selected_model = requested_model or self._resolve_active_model(row)
        if not selected_model:
            raise AppError(
                code="MODEL_NOT_CONFIGURED",
                message="请先为该供应商配置可用模型名",
                status_code=422,
            )

        selection = await self._get_selection()
        selection.active_provider = row.provider
        selection.active_model = selected_model

        await self._db.commit()
        return await self.get_config()

    async def _ensure_defaults(self) -> None:
        provider_rows = await self._list_provider_rows()
        by_provider = {row.provider: row for row in provider_rows}
        dirty = False

        for provider in _PROVIDER_ORDER:
            if provider in by_provider:
                continue
            row = ModelProviderConfig(
                provider=provider,
                enabled=True,
                base_url=_default_base_url(provider),
                api_key_encrypted=None,
                models=_default_models(provider),
                thinking_enabled=True,
                thinking_level=_default_thinking_level(provider),
            )
            self._db.add(row)
            by_provider[provider] = row
            dirty = True

        for row in by_provider.values():
            current_models = row.models or []
            normalized_models = _normalize_model_names(current_models)
            if normalized_models != list(current_models):
                row.models = normalized_models
                dirty = True

        selection = await self._db.get(ModelRuntimeSelection, 1)
        if selection is None:
            openai_row = by_provider[ModelProviderORM.OPENAI]
            selection = ModelRuntimeSelection(
                id=1,
                active_provider=ModelProviderORM.OPENAI,
                active_model=self._resolve_active_model(openai_row),
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
                active_model=None,
            )
            self._db.add(selection)
            await self._db.commit()
        await self._db.refresh(selection)
        return selection

    def _resolve_active_model(self, row: ModelProviderConfig) -> str | None:
        normalized_models = _normalize_model_names(row.models)
        if normalized_models:
            return normalized_models[0]

        default_models = _default_models(row.provider)
        if default_models:
            return default_models[0]
        return None

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
                    models=_normalize_model_names(row.models),
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
