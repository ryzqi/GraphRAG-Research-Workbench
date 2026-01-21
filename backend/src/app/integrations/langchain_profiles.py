"""LangChain 模型 profile 工具。"""

from __future__ import annotations

from app.core.settings import Settings, get_settings


def build_chat_model_profile(settings: Settings | None = None) -> dict | None:
    """根据配置构建 ChatModel profile。

    当使用比例 token 上限时，需要提供 max_input_tokens。
    """
    settings = settings or get_settings()
    max_input_tokens = settings.llm_max_input_tokens
    if not max_input_tokens or max_input_tokens <= 0:
        return None
    return {"max_input_tokens": max_input_tokens}
