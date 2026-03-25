"""KB Chat 图状态的 JSON 安全辅助函数。"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.settings import Settings

logger = logging.getLogger(__name__)


def ensure_json_safe(value: Any, *, settings: Settings, label: str) -> Any:
    """确保值可被 JSON 序列化；按配置决定报错或降级。"""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError) as exc:
        # 非生产环境始终快速失败，尽早暴露 checkpoint 错误。
        if settings.app_env != "prod":
            raise ValueError(f"KB chat state is not JSON-safe: {label}") from exc

        policy = (
            getattr(settings, "kb_chat_json_safe_policy", "fail_fast") or "fail_fast"
        ).lower()
        policy = policy.replace("-", "_")
        if policy == "stringify":
            logger.warning(
                "KB chat state downgraded to JSON-safe", extra={"label": label}
            )
            try:
                return json.loads(json.dumps(value, default=str))
            except Exception:
                return str(value)

        raise ValueError(f"KB chat state is not JSON-safe: {label}") from exc
