"""统一 ChatModel 工厂（按全局模型配置选择 provider）。"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.settings import Settings, get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.integrations.model_runtime_config import (
    ModelRuntimeConfigManager,
    RuntimeProviderConfig,
)
from app.models.model_config import ModelProvider

_DEFAULT_CHAT_PROVIDER_MAX_RETRIES = 2
_DEFAULT_NVIDIA_MAX_RETRIES = 0
_NVIDIA_TIMEOUT_CAP_SECONDS = 60.0
_TIMEOUT_UNSET = object()


def _resolve_timeout_seconds(
    timeout_seconds: float | None | object, default_timeout: float
) -> float | None:
    if timeout_seconds is _TIMEOUT_UNSET:
        return float(default_timeout)
    if isinstance(timeout_seconds, (int, float)):
        return float(timeout_seconds)
    return None


def _supports_ollama_reasoning_level(model_name: str) -> bool:
    normalized = model_name.strip().lower()
    return "gpt-oss" in normalized


def _require_api_key(*, provider_label: str, api_key: str | None) -> str:
    resolved_api_key = (api_key or "").strip()
    if resolved_api_key:
        return resolved_api_key
    raise ModelConfigIncompleteError(
        f"模型配置不完整：{provider_label} API Key 未配置，请前往模型配置页面补全"
    )


def _require_base_url(*, provider_label: str, base_url: str | None) -> str:
    resolved_base_url = (base_url or "").strip()
    if resolved_base_url:
        return resolved_base_url.rstrip("/")
    raise ModelConfigIncompleteError(
        f"模型配置不完整：{provider_label} Base URL 未配置，请前往模型配置页面补全"
    )


def _build_chat_openai_common_kwargs(
    *,
    cfg: Settings,
    provider: ModelProvider,
    model_name: str,
    api_key: str,
    base_url: str,
    timeout_seconds: float | None | object = _TIMEOUT_UNSET,
    max_retries: int | None = None,
) -> dict[str, Any]:
    resolved_max_retries = (
        _DEFAULT_NVIDIA_MAX_RETRIES
        if provider == ModelProvider.NVIDIA
        else _DEFAULT_CHAT_PROVIDER_MAX_RETRIES
    )
    if max_retries is not None:
        resolved_max_retries = max(0, int(max_retries))
    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "max_retries": resolved_max_retries,
    }
    resolved_timeout = _resolve_timeout_seconds(timeout_seconds, cfg.llm_timeout_seconds)
    if resolved_timeout is not None:
        if provider == ModelProvider.NVIDIA:
            resolved_timeout = min(resolved_timeout, _NVIDIA_TIMEOUT_CAP_SECONDS)
        kwargs["timeout"] = resolved_timeout
    profile = build_chat_model_profile(cfg)
    if profile is not None:
        kwargs["profile"] = profile
    return kwargs


def _resolve_model_name(
    *,
    provider: ModelProvider,
    snapshot_model: str | None,
    provider_models: list[str],
) -> str:
    snapshot_candidate = (snapshot_model or "").strip()
    if snapshot_candidate:
        return snapshot_candidate

    for provider_model in provider_models:
        candidate = provider_model.strip()
        if candidate:
            return candidate

    raise ModelConfigIncompleteError(
        f"模型配置不完整：供应商 {provider.value} 缺少可用模型，请前往模型配置页面补全"
    )


def get_active_model_identity(settings: Settings | None = None) -> tuple[str, str]:
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
    if not provider_cfg.enabled:
        raise RuntimeError(
            f"Active model provider is disabled: {provider_cfg.provider.value}"
        )
    return provider_cfg.provider.value, model_name


def create_chat_model_from_runtime_config(
    *,
    provider_cfg: RuntimeProviderConfig,
    model_name: str,
    settings: Settings | None = None,
    use_previous_response_id: bool | None = None,
    timeout_seconds: float | None | object = _TIMEOUT_UNSET,
    max_retries: int | None = None,
) -> BaseChatModel:
    cfg = settings or get_settings()
    if not provider_cfg.enabled:
        raise RuntimeError(
            f"Active model provider is disabled: {provider_cfg.provider.value}"
        )

    if provider_cfg.provider == ModelProvider.OPENAI:
        api_key = _require_api_key(
            provider_label="OpenAI", api_key=provider_cfg.api_key
        )
        base_url = _require_base_url(
            provider_label="OpenAI",
            base_url=provider_cfg.base_url,
        )
        from langchain_openai import ChatOpenAI

        kwargs = _build_chat_openai_common_kwargs(
            cfg=cfg,
            provider=provider_cfg.provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        kwargs["output_version"] = cfg.llm_output_version
        resolved_use_previous_response_id = use_previous_response_id
        if provider_cfg.thinking_enabled:
            if resolved_use_previous_response_id is None:
                resolved_use_previous_response_id = True
        if resolved_use_previous_response_id is not None:
            use_response_replay = bool(resolved_use_previous_response_id)
            kwargs["use_previous_response_id"] = use_response_replay
            # 显式禁用 response_id 重放时，强制走 chat.completions，
            # 避免第三方兼容端把 assistant/output_text 历史判为非法输入。
            kwargs["use_responses_api"] = use_response_replay
        if provider_cfg.thinking_enabled and kwargs.get("use_responses_api", True):
            kwargs["reasoning"] = {
                "effort": provider_cfg.thinking_level or "high",
                "summary": "auto",
            }
        return ChatOpenAI(**kwargs)

    if provider_cfg.provider == ModelProvider.LLAMA_CPP:
        from app.integrations.llamacpp_chat_model import LlamaCppChatOpenAI

        base_url = _require_base_url(
            provider_label="llama.cpp",
            base_url=provider_cfg.base_url,
        )
        api_key = (provider_cfg.api_key or "").strip() or "not-needed"
        kwargs = _build_chat_openai_common_kwargs(
            cfg=cfg,
            provider=provider_cfg.provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        kwargs["use_responses_api"] = False
        return LlamaCppChatOpenAI(**kwargs)

    if provider_cfg.provider == ModelProvider.ANTHROPIC:
        api_key = _require_api_key(
            provider_label="Anthropic",
            api_key=provider_cfg.api_key,
        )
        base_url = _require_base_url(
            provider_label="Anthropic",
            base_url=provider_cfg.base_url,
        )
        from langchain_anthropic import ChatAnthropic

        resolved_max_retries = _DEFAULT_CHAT_PROVIDER_MAX_RETRIES
        if max_retries is not None:
            resolved_max_retries = max(0, int(max_retries))
        kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": api_key,
            "base_url": base_url,
            "max_retries": resolved_max_retries,
        }
        resolved_timeout = _resolve_timeout_seconds(timeout_seconds, cfg.llm_timeout_seconds)
        if resolved_timeout is not None:
            kwargs["timeout"] = resolved_timeout
        profile = build_chat_model_profile(cfg)
        if profile is not None:
            kwargs["profile"] = profile
        if provider_cfg.thinking_enabled and provider_cfg.thinking_level:
            kwargs["effort"] = provider_cfg.thinking_level
        return ChatAnthropic(**kwargs)

    if provider_cfg.provider == ModelProvider.OLLAMA:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "langchain-ollama is not installed; please install it first"
            ) from exc

        base_url = _require_base_url(
            provider_label="Ollama",
            base_url=provider_cfg.base_url,
        )
        kwargs: dict[str, Any] = {
            "model": model_name,
            "base_url": base_url,
        }
        profile = build_chat_model_profile(cfg)
        if profile is not None:
            kwargs["profile"] = profile
        resolved_timeout = _resolve_timeout_seconds(timeout_seconds, cfg.llm_timeout_seconds)
        if resolved_timeout is not None:
            kwargs["sync_client_kwargs"] = {"timeout": resolved_timeout}
            kwargs["async_client_kwargs"] = {"timeout": resolved_timeout}
        if provider_cfg.thinking_enabled:
            if _supports_ollama_reasoning_level(model_name):
                kwargs["reasoning"] = provider_cfg.thinking_level or "high"
            else:
                kwargs["reasoning"] = True
        else:
            kwargs["reasoning"] = False
        return ChatOllama(**kwargs)

    if provider_cfg.provider == ModelProvider.NVIDIA:
        api_key = _require_api_key(
            provider_label="NVIDIA", api_key=provider_cfg.api_key
        )
        base_url = _require_base_url(
            provider_label="NVIDIA",
            base_url=provider_cfg.base_url,
        )
        from langchain_openai import ChatOpenAI

        kwargs = _build_chat_openai_common_kwargs(
            cfg=cfg,
            provider=provider_cfg.provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        kwargs["use_responses_api"] = False
        kwargs["extra_body"] = {
            "chat_template_kwargs": {
                "enable_thinking": bool(provider_cfg.thinking_enabled),
                "clear_thinking": False,
            }
        }
        return ChatOpenAI(**kwargs)

    raise RuntimeError(f"Unsupported model provider: {provider_cfg.provider.value}")


def create_fallback_chat_model(
    *,
    fallback_model_id: str,
    settings: Settings | None = None,
    use_previous_response_id: bool | None = None,
) -> BaseChatModel:
    cfg = settings or get_settings()
    snapshot = ModelRuntimeConfigManager.get_snapshot(settings=cfg)
    normalized_model_id = fallback_model_id.strip()
    if not normalized_model_id:
        raise ModelConfigIncompleteError("fallback_model_id 不能为空")
    if ":" not in normalized_model_id:
        raise ValueError("fallback_model_id must use provider:model format")
    provider_text, model_name = normalized_model_id.split(":", 1)
    provider_text = provider_text.strip()
    model_name = model_name.strip()
    if not provider_text or not model_name:
        raise ValueError("fallback_model_id must use provider:model format")
    try:
        requested_provider = ModelProvider(provider_text)
    except ValueError as exc:
        raise ValueError(f"Unsupported fallback model provider: {provider_text}") from exc

    provider_cfg = snapshot.providers.get(requested_provider)
    if provider_cfg is not None and provider_cfg.enabled and model_name in provider_cfg.models:
        return create_chat_model_from_runtime_config(
            provider_cfg=provider_cfg,
            model_name=model_name,
            settings=cfg,
            use_previous_response_id=use_previous_response_id,
        )

    raise ModelConfigIncompleteError(
        f"fallback_model_id 未匹配任何已启用供应商模型: {normalized_model_id}"
    )


def create_chat_model(
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
    if not provider_cfg.enabled:
        raise RuntimeError(
            f"Active model provider is disabled: {provider_cfg.provider.value}"
        )
    model_name = _resolve_model_name(
        provider=provider_cfg.provider,
        snapshot_model=snapshot.active_model,
        provider_models=provider_cfg.models,
    )
    return create_chat_model_from_runtime_config(
        provider_cfg=provider_cfg,
        model_name=model_name,
        settings=cfg,
        use_previous_response_id=use_previous_response_id,
    )
