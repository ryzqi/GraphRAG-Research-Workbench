"""统一 ChatModel 工厂（按全局模型配置选择 provider）。"""

from __future__ import annotations

from typing import Any
import warnings

from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.settings import Settings, get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.model_config import ModelProvider


_NVIDIA_KIMI_K2_5_MODEL = "moonshotai/kimi-k2.5"
_NVIDIA_KIMI_K2_5_DEFAULTS: dict[str, Any] = {
    "temperature": 1,
    "top_p": 1,
    "max_completion_tokens": 16384,
}
_NVIDIA_KIMI_K2_5_UNKNOWN_TYPE_WARNING = (
    r"Found moonshotai/kimi-k2\.5 in available_models, but type is unknown and inference may fail\."
)


def _supports_ollama_reasoning_level(model_name: str) -> bool:
    normalized = model_name.strip().lower()
    return "gpt-oss" in normalized


def _supports_nvidia_thinking_mode(model: Any) -> bool:
    """仅当 NVIDIA 模型元数据明确声明支持 thinking 模式时返回 True。"""
    support = getattr(getattr(getattr(model, "_client", None), "model", None), "supports_thinking", None)
    return support is True


def _is_nvidia_kimi_k2_5(model_name: str) -> bool:
    return model_name.strip().lower() == _NVIDIA_KIMI_K2_5_MODEL


def _enable_kimi_runtime_capabilities(model: Any) -> None:
    metadata = getattr(getattr(model, "_client", None), "model", None)
    if metadata is None:
        return
    # Kimi k2.5 支持 tools / structured output，但元数据可能滞后。
    for key in ("supports_tools", "supports_structured_output"):
        if getattr(metadata, key, None) is False:
            setattr(metadata, key, True)


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
        raise RuntimeError(f"Active model provider is disabled: {provider_cfg.provider.value}")
    return provider_cfg.provider.value, model_name


def create_chat_model(
    *,
    settings: Settings | None = None,
    use_previous_response_id: bool | None = None,
) -> Any:
    cfg = settings or get_settings()
    snapshot = ModelRuntimeConfigManager.get_snapshot(settings=cfg)
    try:
        provider_cfg = snapshot.active_provider_config()
    except RuntimeError as exc:
        raise ModelConfigIncompleteError(
            "模型配置不完整：没有可用的已启用供应商，请前往模型配置页面补全"
        ) from exc
    if not provider_cfg.enabled:
        raise RuntimeError(f"Active model provider is disabled: {provider_cfg.provider.value}")
    model_name = _resolve_model_name(
        provider=provider_cfg.provider,
        snapshot_model=snapshot.active_model,
        provider_models=provider_cfg.models,
    )
    if provider_cfg.provider == ModelProvider.OPENAI:
        api_key = (provider_cfg.api_key or "").strip()
        if not api_key:
            raise ModelConfigIncompleteError(
                "模型配置不完整：OpenAI API Key 未配置，请前往模型配置页面补全"
            )
        base_url = (provider_cfg.base_url or "").strip()
        if not base_url:
            raise ModelConfigIncompleteError(
                "模型配置不完整：OpenAI Base URL 未配置，请前往模型配置页面补全"
            )
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": api_key,
            "base_url": base_url.rstrip("/"),
            "timeout": cfg.llm_timeout_seconds,
            "max_retries": 2,
            "output_version": cfg.llm_output_version,
        }
        profile = build_chat_model_profile(cfg)
        if profile is not None:
            kwargs["profile"] = profile
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
        profile = build_chat_model_profile(cfg)
        if profile is not None:
            kwargs["profile"] = profile
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
        profile = build_chat_model_profile(cfg)
        if profile is not None:
            kwargs["profile"] = profile
        if provider_cfg.api_key:
            kwargs["api_key"] = provider_cfg.api_key
        if provider_cfg.base_url:
            kwargs["base_url"] = provider_cfg.base_url
        if _is_nvidia_kimi_k2_5(model_name):
            kwargs.update(_NVIDIA_KIMI_K2_5_DEFAULTS)
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=_NVIDIA_KIMI_K2_5_UNKNOWN_TYPE_WARNING,
                    category=UserWarning,
                )
                model = ChatNVIDIA(**kwargs)
            _enable_kimi_runtime_capabilities(model)
        else:
            model = ChatNVIDIA(**kwargs)
        if provider_cfg.thinking_enabled and _is_nvidia_kimi_k2_5(model_name):
            return model.bind(chat_template_kwargs={"thinking": True})
        if provider_cfg.thinking_enabled and hasattr(model, "with_thinking_mode"):
            if not _supports_nvidia_thinking_mode(model):
                return model
            with_thinking_mode = getattr(model, "with_thinking_mode")
            try:
                return with_thinking_mode(enabled=True)
            except Exception:
                return model
        return model

    raise RuntimeError(f"Unsupported model provider: {provider_cfg.provider.value}")
