"""运行时模型配置缓存管理。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.secrets import decrypt_secret, resolve_model_config_kms_key
from app.core.settings import Settings, get_settings
from app.db.session import get_sessionmaker
from app.models.model_config import (
    ModelProvider,
    ModelProviderConfig,
    ModelRuntimeSelection,
)

logger = logging.getLogger(__name__)

_PROVIDER_PRIORITY: tuple[ModelProvider, ...] = (
    ModelProvider.OPENAI,
    ModelProvider.OLLAMA,
    ModelProvider.NVIDIA,
)


def _normalize_model_names(values: list[str] | None) -> list[str]:
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


def _provider_priority(provider: ModelProvider) -> int:
    try:
        return _PROVIDER_PRIORITY.index(provider)
    except ValueError:
        return len(_PROVIDER_PRIORITY)


def _ordered_provider_configs(
    providers: dict[ModelProvider, "RuntimeProviderConfig"],
) -> list["RuntimeProviderConfig"]:
    ordered = sorted(providers.values(), key=lambda item: _provider_priority(item.provider))
    return ordered


def _resolve_active_provider(
    *,
    providers: dict[ModelProvider, "RuntimeProviderConfig"],
    requested_provider: ModelProvider | None,
) -> ModelProvider:
    if requested_provider is not None:
        preferred = providers.get(requested_provider)
        if preferred is not None and preferred.enabled:
            return requested_provider

    for cfg in _ordered_provider_configs(providers):
        if cfg.enabled:
            return cfg.provider

    if requested_provider is not None and requested_provider in providers:
        return requested_provider

    ordered = _ordered_provider_configs(providers)
    if ordered:
        return ordered[0].provider
    raise RuntimeError("No model provider configuration rows found")


@dataclass(frozen=True, slots=True)
class RuntimeProviderConfig:
    provider: ModelProvider
    enabled: bool
    base_url: str | None
    api_key: str | None
    models: list[str]
    thinking_enabled: bool
    thinking_level: str | None


@dataclass(frozen=True, slots=True)
class RuntimeModelSnapshot:
    providers: dict[ModelProvider, RuntimeProviderConfig]
    active_provider: ModelProvider
    active_model: str | None
    updated_at: datetime | None

    def active_provider_config(self) -> RuntimeProviderConfig:
        cfg = self.providers.get(self.active_provider)
        if cfg is not None and cfg.enabled:
            return cfg
        for candidate in _ordered_provider_configs(self.providers):
            if candidate.enabled:
                return candidate
        raise RuntimeError("No enabled model provider configured")


class ModelRuntimeConfigManager:
    """运行时模型配置缓存（进程级）。"""

    _snapshot: RuntimeModelSnapshot | None = None
    _initialized: bool = False
    _lock = asyncio.Lock()
    _sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    async def initialize(
        cls,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        settings: Settings | None = None,
    ) -> None:
        if cls._initialized:
            return
        cls._sessionmaker = sessionmaker or get_sessionmaker()
        await cls.refresh(settings=settings)
        cls._initialized = True

    @classmethod
    async def refresh(
        cls,
        *,
        db: AsyncSession | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        async with cls._lock:
            try:
                if db is not None:
                    cls._snapshot = await cls._load_snapshot(db=db, settings=cfg)
                    return

                sessionmaker = cls._sessionmaker or get_sessionmaker()
                async with sessionmaker() as session:
                    cls._snapshot = await cls._load_snapshot(db=session, settings=cfg)
            except Exception as exc:
                logger.warning("加载模型运行时配置失败，使用回退配置", extra={"error": str(exc)})
                cls._snapshot = cls._build_fallback_snapshot(cfg)

    @classmethod
    def get_snapshot(cls, *, settings: Settings | None = None) -> RuntimeModelSnapshot:
        if cls._snapshot is not None:
            return cls._snapshot
        return cls._build_fallback_snapshot(settings or get_settings())

    @classmethod
    async def shutdown(cls) -> None:
        async with cls._lock:
            cls._snapshot = None
            cls._initialized = False
            cls._sessionmaker = None

    @classmethod
    async def _load_snapshot(
        cls,
        *,
        db: AsyncSession,
        settings: Settings,
    ) -> RuntimeModelSnapshot:
        kms_key = resolve_model_config_kms_key(settings)
        result = await db.execute(select(ModelProviderConfig))
        rows = list(result.scalars().all())
        if not rows:
            return cls._build_fallback_snapshot(settings)
        rows.sort(key=lambda row: _provider_priority(row.provider))

        providers: dict[ModelProvider, RuntimeProviderConfig] = {}
        for row in rows:
            api_key = None
            if row.api_key_encrypted:
                try:
                    api_key = decrypt_secret(row.api_key_encrypted, kms_key=kms_key)
                except Exception:
                    api_key = None

            thinking_level = row.thinking_level
            if not thinking_level and row.provider in {
                ModelProvider.OPENAI,
                ModelProvider.OLLAMA,
            }:
                thinking_level = "high"

            providers[row.provider] = RuntimeProviderConfig(
                provider=row.provider,
                enabled=row.enabled,
                base_url=row.base_url,
                api_key=api_key,
                models=_normalize_model_names(row.models),
                thinking_enabled=row.thinking_enabled,
                thinking_level=thinking_level,
            )

        selection = await db.get(ModelRuntimeSelection, 1)
        active_provider = _resolve_active_provider(
            providers=providers,
            requested_provider=selection.active_provider if selection is not None else None,
        )

        provider_cfg = providers[active_provider]
        selection_matches_active = (
            selection is not None and selection.active_provider == active_provider
        )
        active_model = (
            selection.active_model.strip()
            if (
                selection_matches_active
                and isinstance(selection.active_model, str)
                and selection.active_model.strip() in provider_cfg.models
            )
            else None
        )
        if not active_model:
            if provider_cfg.models:
                active_model = provider_cfg.models[0]
            elif active_provider == ModelProvider.OPENAI:
                active_model = settings.llm_model.strip() or None
            else:
                active_model = None

        return RuntimeModelSnapshot(
            providers=providers,
            active_provider=active_provider,
            active_model=active_model,
            updated_at=selection.updated_at if selection else None,
        )

    @staticmethod
    def _build_fallback_snapshot(settings: Settings) -> RuntimeModelSnapshot:
        provider_cfg = RuntimeProviderConfig(
            provider=ModelProvider.OPENAI,
            enabled=True,
            base_url=settings.llm_base_url.rstrip("/"),
            api_key=settings.llm_api_key,
            models=_normalize_model_names([settings.llm_model]),
            thinking_enabled=True,
            thinking_level="high",
        )
        return RuntimeModelSnapshot(
            providers={ModelProvider.OPENAI: provider_cfg},
            active_provider=ModelProvider.OPENAI,
            active_model=provider_cfg.models[0] if provider_cfg.models else None,
            updated_at=None,
        )
