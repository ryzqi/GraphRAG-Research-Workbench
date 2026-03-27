"""模型可用性健康探针。"""

from __future__ import annotations

from typing import Any

from langchain.messages import HumanMessage

from app.core.errors import AppError
from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_factory import create_chat_model_from_runtime_config
from app.integrations.model_runtime_config import RuntimeProviderConfig

_MODEL_PROBE_TIMEOUT_SECONDS = 20.0
_MODEL_PROBE_MAX_RETRIES = 0
_MODEL_PROBE_PROMPT = "只回复 OK"


def _probe_details(
    *, provider_cfg: RuntimeProviderConfig, model_name: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "provider": provider_cfg.provider.value,
        "model": model_name,
        "timeout_seconds": _MODEL_PROBE_TIMEOUT_SECONDS,
        **(extra or {}),
    }


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _map_probe_exception(
    *,
    exc: Exception,
    provider_cfg: RuntimeProviderConfig,
    model_name: str,
) -> AppError:
    mod = exc.__class__.__module__ or ""
    if mod.startswith("openai"):
        exc_type = type(exc).__name__
        if exc_type == "APITimeoutError":
            return AppError(
                code="MODEL_PROBE_TIMEOUT",
                message=(
                    f"模型健康检查超时：{provider_cfg.provider.value}/{model_name} 在 "
                    f"{int(_MODEL_PROBE_TIMEOUT_SECONDS)} 秒内未返回响应。"
                    "该模型可能仅出现在目录中，但当前账号/路由下不可实际推理。"
                ),
                status_code=504,
                details=_probe_details(
                    provider_cfg=provider_cfg,
                    model_name=model_name,
                    extra={"exc_type": exc_type},
                ),
            )
        if exc_type == "APIConnectionError":
            return AppError(
                code="MODEL_PROBE_CONNECTION_FAILED",
                message=(
                    f"模型健康检查连接失败：{provider_cfg.provider.value}/{model_name} "
                    "无法连接上游服务，请检查 Base URL、网络连通性或服务状态。"
                ),
                status_code=503,
                details=_probe_details(
                    provider_cfg=provider_cfg,
                    model_name=model_name,
                    extra={"exc_type": exc_type},
                ),
            )

        status_code = _extract_status_code(exc)
        if status_code in {401, 403}:
            return AppError(
                code="MODEL_PROBE_AUTH_FAILED",
                message=(
                    f"模型健康检查鉴权失败：{provider_cfg.provider.value}/{model_name} "
                    "请检查 API Key 与 Base URL 配置。"
                ),
                status_code=422,
                details=_probe_details(
                    provider_cfg=provider_cfg,
                    model_name=model_name,
                    extra={"upstream_status_code": status_code},
                ),
            )
        if status_code == 429:
            return AppError(
                code="MODEL_PROBE_RATE_LIMITED",
                message=(
                    f"模型健康检查被限流：{provider_cfg.provider.value}/{model_name} "
                    "当前请求过于频繁，请稍后重试。"
                ),
                status_code=503,
                details=_probe_details(
                    provider_cfg=provider_cfg,
                    model_name=model_name,
                    extra={"upstream_status_code": status_code},
                ),
            )
        if isinstance(status_code, int) and status_code >= 500:
            return AppError(
                code="MODEL_PROBE_UPSTREAM_ERROR",
                message=(
                    f"模型健康检查失败：{provider_cfg.provider.value}/{model_name} "
                    "对应的上游模型暂时不可用，请稍后重试或更换模型。"
                ),
                status_code=503,
                details=_probe_details(
                    provider_cfg=provider_cfg,
                    model_name=model_name,
                    extra={"upstream_status_code": status_code},
                ),
            )

    return AppError(
        code="MODEL_PROBE_FAILED",
        message=(
            f"模型健康检查失败：{provider_cfg.provider.value}/{model_name} "
            "无法完成最小推理，请确认模型名、供应商配置与上游状态。"
        ),
        status_code=502,
        details=_probe_details(
            provider_cfg=provider_cfg,
            model_name=model_name,
            extra={"exc_type": type(exc).__name__},
        ),
    )


def _has_probe_content(response: Any) -> bool:
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and item.strip():
                return True
            if isinstance(item, dict):
                for key in ("text", "content"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        return True
    return False


async def probe_runtime_target(
    *,
    provider_cfg: RuntimeProviderConfig,
    model_name: str,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    chat_model = create_chat_model_from_runtime_config(
        provider_cfg=provider_cfg,
        model_name=model_name,
        settings=cfg,
        timeout_seconds=_MODEL_PROBE_TIMEOUT_SECONDS,
        max_retries=_MODEL_PROBE_MAX_RETRIES,
    )

    try:
        response = await chat_model.ainvoke([HumanMessage(content=_MODEL_PROBE_PROMPT)])
    except ModelConfigIncompleteError:
        raise
    except AppError:
        raise
    except Exception as exc:
        raise _map_probe_exception(
            exc=exc,
            provider_cfg=provider_cfg,
            model_name=model_name,
        ) from exc

    if _has_probe_content(response):
        return

    raise AppError(
        code="MODEL_PROBE_EMPTY_RESPONSE",
        message=(
            f"模型健康检查失败：{provider_cfg.provider.value}/{model_name} "
            "未返回有效内容，请稍后重试或更换模型。"
        ),
        status_code=502,
        details=_probe_details(provider_cfg=provider_cfg, model_name=model_name),
    )
