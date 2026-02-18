"""统一 ChatModel 工厂（按全局模型配置选择 provider）。"""

from __future__ import annotations

from typing import Any

from app.core.settings import Settings, get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.model_config import ModelProvider


def _supports_ollama_reasoning_level(model_name: str) -> bool:
    normalized = model_name.strip().lower()
    return "gpt-oss" in normalized


def _resolve_model_name(
    *,
    provider: ModelProvider,
    snapshot_model: str | None,
    provider_models: list[str],
    fallback_openai_model: str,
) -> str:
    snapshot_candidate = (snapshot_model or "").strip()
    if snapshot_candidate:
        return snapshot_candidate

    for provider_model in provider_models:
        candidate = provider_model.strip()
        if candidate:
            return candidate

    if provider == ModelProvider.OPENAI:
        openai_model = fallback_openai_model.strip()
        if openai_model:
            return openai_model

    raise RuntimeError(f"No model configured for provider: {provider.value}")


def get_active_model_identity(settings: Settings | None = None) -> tuple[str, str]:
    cfg = settings or get_settings()
    snapshot = ModelRuntimeConfigManager.get_snapshot(settings=cfg)
    provider_cfg = snapshot.active_provider_config()
    model_name = _resolve_model_name(
        provider=provider_cfg.provider,
        snapshot_model=snapshot.active_model,
        provider_models=provider_cfg.models,
        fallback_openai_model=cfg.llm_model,
    )
    if not provider_cfg.enabled:
        raise RuntimeError(f"Active model provider is disabled: {provider_cfg.provider.value}")
    return provider_cfg.provider.value, model_name


def create_chat_model(*, settings: Settings | None = None) -> Any:
    cfg = settings or get_settings()
    snapshot = ModelRuntimeConfigManager.get_snapshot(settings=cfg)
    provider_cfg = snapshot.active_provider_config()
    if not provider_cfg.enabled:
        raise RuntimeError(f"Active model provider is disabled: {provider_cfg.provider.value}")
    model_name = _resolve_model_name(
        provider=provider_cfg.provider,
        snapshot_model=snapshot.active_model,
        provider_models=provider_cfg.models,
        fallback_openai_model=cfg.llm_model,
    )

    if provider_cfg.provider == ModelProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": provider_cfg.api_key or cfg.llm_api_key,
            "base_url": (provider_cfg.base_url or cfg.llm_base_url).rstrip("/"),
            "timeout": cfg.llm_timeout_seconds,
            "max_retries": 2,
        }
        profile = build_chat_model_profile(cfg)
        if profile is not None:
            kwargs["profile"] = profile
        if provider_cfg.thinking_enabled:
            kwargs["reasoning"] = {
                "effort": provider_cfg.thinking_level or "high",
                "summary": "auto",
            }
        return ChatOpenAI(**kwargs)

    if provider_cfg.provider == ModelProvider.OLLAMA:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "langchain-ollama is not installed; please install it first"
            ) from exc

        kwargs = {
            "model": model_name,
            "base_url": provider_cfg.base_url or "http://127.0.0.1:11434",
        }
        if provider_cfg.thinking_enabled:
            if _supports_ollama_reasoning_level(model_name):
                kwargs["reasoning"] = provider_cfg.thinking_level or "high"
            else:
                kwargs["reasoning"] = True
        else:
            kwargs["reasoning"] = False
        return ChatOllama(**kwargs)

    if provider_cfg.provider == ModelProvider.NVIDIA:
        try:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "langchain-nvidia-ai-endpoints is not installed; please install it first"
            ) from exc

        kwargs = {"model": model_name}
        if provider_cfg.api_key:
            kwargs["api_key"] = provider_cfg.api_key
        if provider_cfg.base_url:
            kwargs["base_url"] = provider_cfg.base_url
        model = ChatNVIDIA(**kwargs)
        if provider_cfg.thinking_enabled and hasattr(model, "with_thinking_mode"):
            with_thinking_mode = getattr(model, "with_thinking_mode")
            try:
                return with_thinking_mode(enabled=True)
            except Exception:
                return model
        return model

    raise RuntimeError(f"Unsupported model provider: {provider_cfg.provider.value}")
