"""KB Chat 自建 LangGraph 模型调用保护。"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from app.agents.model_safety import resolve_fallback_chat_model
from app.core.settings import Settings


class KbChatModelCallLimitExceeded(RuntimeError):
    """KB Chat 单次运行模型调用数超过配置上限。"""


class KbChatGuardedChatModel:
    def __init__(
        self,
        primary_model: BaseChatModel,
        *,
        settings: Settings,
        fallback_model: BaseChatModel | None,
        call_state: dict[str, int] | None = None,
    ) -> None:
        self._primary_model = primary_model
        self._settings = settings
        self._fallback_model = fallback_model
        self._call_state = call_state if call_state is not None else {"run_calls": 0}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary_model, name)

    def bind(self, **kwargs: Any) -> "KbChatGuardedChatModel":
        return KbChatGuardedChatModel(
            self._primary_model.bind(**kwargs),
            settings=self._settings,
            fallback_model=self._fallback_model.bind(**kwargs)
            if self._fallback_model is not None
            else None,
            call_state=self._call_state,
        )

    def with_structured_output(self, *args: Any, **kwargs: Any) -> "KbChatGuardedChatModel":
        return KbChatGuardedChatModel(
            self._primary_model.with_structured_output(*args, **kwargs),
            settings=self._settings,
            fallback_model=self._fallback_model.with_structured_output(*args, **kwargs)
            if self._fallback_model is not None
            else None,
            call_state=self._call_state,
        )

    def _coerce_config(self, config: Any) -> RunnableConfig:
        if isinstance(config, dict):
            metadata = config.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata = {
                **metadata,
                "kb_chat_model_guard": {
                    "run_calls": self._call_state["run_calls"],
                    "run_limit": self._settings.kb_chat_run_model_call_limit,
                    "fallback_enabled": self._fallback_model is not None,
                },
            }
            return {**config, "metadata": metadata}
        return {
            "metadata": {
                "kb_chat_model_guard": {
                    "run_calls": self._call_state["run_calls"],
                    "run_limit": self._settings.kb_chat_run_model_call_limit,
                    "fallback_enabled": self._fallback_model is not None,
                }
            }
        }

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        limit = self._settings.kb_chat_run_model_call_limit
        if limit is not None and self._call_state["run_calls"] >= int(limit):
            raise KbChatModelCallLimitExceeded(
                f"KB Chat run model call limit exceeded: {limit}"
            )
        self._call_state["run_calls"] += 1
        config = kwargs.get("config")
        kwargs["config"] = self._coerce_config(config)
        try:
            return await self._primary_model.ainvoke(*args, **kwargs)
        except Exception:
            if self._fallback_model is None:
                raise
            return await self._fallback_model.ainvoke(*args, **kwargs)


def guard_kb_chat_model(
    chat_model: BaseChatModel,
    *,
    settings: Settings,
) -> KbChatGuardedChatModel:
    return KbChatGuardedChatModel(
        chat_model,
        settings=settings,
        fallback_model=resolve_fallback_chat_model(
            settings=settings,
            fallback_model_id=settings.kb_chat_fallback_model_id,
            use_previous_response_id=False,
        ),
    )
