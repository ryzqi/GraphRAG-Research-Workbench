"""ChatModel 指纹缓存。"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_factory import (
    _DEFAULT_CHAT_PROVIDER_MAX_RETRIES,
    _DEFAULT_NVIDIA_MAX_RETRIES,
    _NVIDIA_TIMEOUT_CAP_SECONDS,
    _resolve_model_name,
    create_chat_model_from_runtime_config,
)
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.model_config import ModelProvider


@dataclass(frozen=True, slots=True)
class _CacheKey:
    provider: str
    model: str
    api_key_hash: str
    base_url: str
    timeout_seconds: float | None
    max_retries: int
    thinking_enabled: bool
    thinking_level: str | None
    use_previous_response_id_marker: str
    output_version: str
    runtime_version: int


def _hash_key(value: str | None) -> str:
    if not value:
        return "0"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _previous_response_id_marker(value: bool | None) -> str:
    if value is None:
        return "unset"
    return "true" if value else "false"


def _resolve_timeout_for_key(
    *,
    settings: Settings,
    provider: ModelProvider,
) -> float | None:
    resolved = float(settings.llm_timeout_seconds)
    if provider == ModelProvider.NVIDIA:
        return min(resolved, _NVIDIA_TIMEOUT_CAP_SECONDS)
    return resolved


def _resolve_max_retries_for_key(provider: ModelProvider) -> int:
    if provider == ModelProvider.NVIDIA:
        return _DEFAULT_NVIDIA_MAX_RETRIES
    return _DEFAULT_CHAT_PROVIDER_MAX_RETRIES


class ChatModelCache:
    """进程级 ChatModel 缓存。"""

    _models: dict[_CacheKey, BaseChatModel] = {}
    _lock = threading.Lock()
    _hits = 0
    _misses = 0

    @classmethod
    def get_or_build(
        cls,
        *,
        settings: Settings | None = None,
        use_previous_response_id: bool | None = None,
    ) -> BaseChatModel:
        cfg = settings or get_settings()
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=cfg)
        try:
            provider_cfg = snapshot.active_provider_config()
        except RuntimeError as exc:
            raise ModelConfigIncompleteError(
                "模型配置不完整：没有可用的已启用供应商，请前往模型配置页面补全"
            ) from exc
        model_name = _resolve_model_name(
            provider=provider_cfg.provider,
            snapshot_model=snapshot.active_model,
            provider_models=provider_cfg.models,
        )
        key = _CacheKey(
            provider=provider_cfg.provider.value,
            model=model_name,
            api_key_hash=_hash_key(provider_cfg.api_key),
            base_url=(provider_cfg.base_url or "").rstrip("/"),
            timeout_seconds=_resolve_timeout_for_key(
                settings=cfg,
                provider=provider_cfg.provider,
            ),
            max_retries=_resolve_max_retries_for_key(provider_cfg.provider),
            thinking_enabled=bool(provider_cfg.thinking_enabled),
            thinking_level=provider_cfg.thinking_level or None,
            use_previous_response_id_marker=_previous_response_id_marker(
                use_previous_response_id
            ),
            output_version=str(cfg.llm_output_version or ""),
            runtime_version=int(getattr(snapshot, "version", 0)),
        )
        with cls._lock:
            cached = cls._models.get(key)
            if cached is not None:
                cls._hits += 1
                return cached
        model = create_chat_model_from_runtime_config(
            provider_cfg=provider_cfg,
            model_name=model_name,
            settings=cfg,
            use_previous_response_id=use_previous_response_id,
        )
        with cls._lock:
            existing = cls._models.get(key)
            if existing is not None:
                cls._hits += 1
                return existing
            cls._models[key] = model
            cls._misses += 1
            stale_keys = [
                stale_key
                for stale_key in list(cls._models)
                if stale_key.runtime_version < key.runtime_version
            ]
            for stale_key in stale_keys:
                cls._models.pop(stale_key, None)
            return model

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._models.clear()
            cls._hits = 0
            cls._misses = 0

    @classmethod
    def stats(cls) -> dict[str, int]:
        with cls._lock:
            return {
                "hits": cls._hits,
                "misses": cls._misses,
                "size": len(cls._models),
            }


def create_chat_model_cached(
    *,
    settings: Settings | None = None,
    use_previous_response_id: bool | None = None,
) -> BaseChatModel:
    return ChatModelCache.get_or_build(
        settings=settings,
        use_previous_response_id=use_previous_response_id,
    )
