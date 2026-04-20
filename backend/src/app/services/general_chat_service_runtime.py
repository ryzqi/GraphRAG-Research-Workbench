from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from langchain.agents.middleware.summarization import ContextSize
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from sqlalchemy import select

from app.agents.general_chat_agent import DEFAULT_SUMMARY_KEEP_MESSAGES, SUMMARY_TRIGGER
from app.agents.tool_calling.registry import build_tool_registry_cached
from app.agents.tools.system_time import build_system_time_tool
from app.agents.tools.web_search import has_web_extract_provider, has_web_search_provider
from app.core.errors import AppError
from app.core.model_config_errors import ModelConfigIncompleteError
from app.integrations.mcp_adapters import open_mcp_tool_runtime
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.model_config import ModelProvider
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.services.chat_replay_policy import ReplayDecision, ReplayMode, decide_replay_mode
from app.services.general_chat_service_contracts import SUMMARY_META_FLAG
from app.services.general_chat_service_execution import _is_previous_response_not_found_error
from app.services.message_normalizer import extract_response_id, extract_text_content
from app.utils.token_counter import count_tokens_approximately

logger = logging.getLogger(__name__)


async def _load_tool_registry_for_session(
    self, *, session: ChatSession
) -> tuple[list[Any], dict[str, Any]]:
    include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
    include_web_search = has_web_search_provider(self._settings)
    include_web_extract = has_web_extract_provider(self._settings)
    extensions: list[ToolExtension] = []
    if include_mcp:
        stmt = select(ToolExtension).where(
            ToolExtension.status == ExtensionStatus.ENABLED
        )
        result = await self._db.execute(stmt)
        extensions = list(result.scalars().all())
    return await build_tool_registry_cached(
        settings=self._settings,
        extensions=extensions,
        extra_tools=[build_system_time_tool()],
        include_web_search=include_web_search,
        include_web_extract=include_web_extract,
        include_web_crawl=False,
        include_mcp=include_mcp,
        redis=self._redis,
        http_client=self._http_client,
    )


@asynccontextmanager
async def _load_runtime_tool_registry_for_session(self, *, session: ChatSession):
    include_mcp = bool(session.allow_external and self._settings.mcp_enabled)
    include_web_search = has_web_search_provider(self._settings)
    include_web_extract = has_web_extract_provider(self._settings)
    extensions: list[ToolExtension] = []
    if include_mcp:
        stmt = select(ToolExtension).where(
            ToolExtension.status == ExtensionStatus.ENABLED
        )
        result = await self._db.execute(stmt)
        extensions = list(result.scalars().all())

    if not include_mcp:
        yield await build_tool_registry_cached(
            settings=self._settings,
            extensions=[],
            extra_tools=[build_system_time_tool()],
            include_web_search=include_web_search,
            include_web_extract=include_web_extract,
            include_web_crawl=False,
            include_mcp=False,
            redis=self._redis,
            http_client=self._http_client,
        )
        return

    async with open_mcp_tool_runtime(
        settings=self._settings,
        extensions=extensions,
        allow_external=True,
    ) as (mcp_entries, _diagnostics):
        yield await build_tool_registry_cached(
            settings=self._settings,
            extensions=extensions,
            mcp_entries=mcp_entries,
            extra_tools=[build_system_time_tool()],
            include_web_search=include_web_search,
            include_web_extract=include_web_extract,
            include_web_crawl=False,
            include_mcp=True,
            redis=self._redis,
            http_client=self._http_client,
        )


async def _open_runtime_tool_registry_for_session(
    self, *, session: ChatSession
) -> tuple[list[Any], dict[str, Any]]:
    await self._close_runtime_tool_registry()
    runtime_cm = self._load_runtime_tool_registry_for_session(session=session)
    tools, tool_meta_by_name = await runtime_cm.__aenter__()
    self._active_tool_runtime_cm = runtime_cm
    return tools, tool_meta_by_name


async def _close_runtime_tool_registry(self) -> None:
    runtime_cm = getattr(self, "_active_tool_runtime_cm", None)
    if runtime_cm is None:
        return
    self._active_tool_runtime_cm = None
    await runtime_cm.__aexit__(None, None, None)


async def _load_history(
    self, session_id: uuid.UUID, limit: int | None
) -> list[AnyMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit * 2)
    result = await self._db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    filtered = [m for m in messages if not self._is_summary_message(m)]
    if limit is not None and len(filtered) > limit:
        filtered = filtered[-limit:]
    history: list[AnyMessage] = []
    for msg in filtered:
        if msg.role == MessageRole.SYSTEM:
            history.append(SystemMessage(content=msg.content))
            continue
        if msg.role == MessageRole.ASSISTANT:
            response_id = (
                str((msg.meta or {}).get("response_id")).strip()
                if isinstance(msg.meta, dict)
                and isinstance((msg.meta or {}).get("response_id"), str)
                and str((msg.meta or {}).get("response_id")).strip()
                else ""
            )
            if response_id:
                history.append(
                    AIMessage(
                        content=msg.content,
                        response_metadata={"id": response_id},
                    )
                )
            else:
                history.append(AIMessage(content=msg.content))
            continue
        history.append(HumanMessage(content=msg.content))
    return history


@staticmethod
def _is_summary_message(msg: ChatMessage) -> bool:
    return bool((msg.meta or {}).get(SUMMARY_META_FLAG))


def _build_summary_trigger(self) -> ContextSize | list[ContextSize]:
    if self._settings.llm_max_input_tokens:
        return SUMMARY_TRIGGER
    triggers: list[ContextSize] = []
    min_messages = self._settings.summary_trigger_min_messages
    min_tokens = self._settings.summary_trigger_min_tokens
    if min_messages > 0:
        triggers.append(("messages", min_messages))
    if min_tokens > 0:
        triggers.append(("tokens", min_tokens))
    if not triggers:
        return (
            "messages",
            int(
                getattr(
                    self._settings,
                    "summary_keep_messages",
                    DEFAULT_SUMMARY_KEEP_MESSAGES,
                )
                or DEFAULT_SUMMARY_KEEP_MESSAGES
            ),
        )
    return triggers[0] if len(triggers) == 1 else triggers


@staticmethod
def _map_llm_exception(exc: Exception) -> AppError | None:
    """将 OpenAI 兼容端点的上游异常映射为可预期的 AppError。"""
    mod = exc.__class__.__module__ or ""
    if not mod.startswith("openai"):
        return None
    exc_type = type(exc).__name__
    if exc_type == "APITimeoutError":
        return AppError(
            code="LLM_UPSTREAM_TIMEOUT",
            message="上游大模型服务响应超时，请稍后重试；若频繁出现，请在模型配置中调大超时时间或关闭思考模式",
            status_code=504,
            details={"exc_type": exc_type},
        )
    if exc_type == "APIConnectionError":
        return AppError(
            code="LLM_CONNECTION_ERROR",
            message="大模型服务连接失败，请检查 Base URL、网络连通性或上游服务状态",
            status_code=503,
            details={"exc_type": exc_type},
        )

    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

    if isinstance(status_code, int):
        if (
            status_code == 404
            and _is_previous_response_not_found_error(exc)
        ):
            return AppError(
                code="CHAT_REPLAY_STATE_EXPIRED",
                message="对话状态已过期，请重试当前问题",
                status_code=409,
                details={"upstream_status_code": status_code},
            )
        if status_code in {401, 403}:
            return AppError(
                code="LLM_AUTH_ERROR",
                message="大模型服务鉴权失败，请前往“模型配置”页面检查 API Key / Base URL 配置",
                status_code=500,
                details={"upstream_status_code": status_code},
            )
        if status_code == 429:
            return AppError(
                code="LLM_RATE_LIMITED",
                message="大模型服务请求过于频繁，请稍后重试",
                status_code=503,
                details={"upstream_status_code": status_code},
            )
        if status_code >= 500:
            return AppError(
                code="LLM_UPSTREAM_ERROR",
                message="上游大模型服务暂时不可用，请稍后重试",
                status_code=503,
                details={"upstream_status_code": status_code},
            )

    return None


@staticmethod
def _build_agent_messages(
    history: list[AnyMessage], user_content: str
) -> list[AnyMessage]:
    messages = list(history)
    messages.append(HumanMessage(content=user_content))
    return messages


@staticmethod
def _message_text_for_metrics(message: object) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    text = extract_text_content(content, include_output_text=True)
    if text:
        return text
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def _resolve_replay_decision(self) -> ReplayDecision:
    snapshot = ModelRuntimeConfigManager.get_snapshot(settings=self._settings)
    try:
        provider_cfg = snapshot.active_provider_config()
    except RuntimeError as exc:
        raise ModelConfigIncompleteError(
            "模型配置不完整：没有可用的已启用供应商，请前往模型配置页面补全"
        ) from exc
    configured_mode = self._settings.general_chat_replay_mode
    decision = decide_replay_mode(
        configured_mode=self._settings.general_chat_replay_mode,
        provider=provider_cfg.provider,
        thinking_enabled=provider_cfg.thinking_enabled,
    )
    if (
        configured_mode == ReplayMode.AUTO.value
        and decision.mode == ReplayMode.RESPONSE_ID
        and provider_cfg.provider == ModelProvider.OPENAI
        and not self._supports_openai_response_replay(provider_cfg.base_url)
    ):
        logger.info(
            "General chat replay auto-downgraded to manual for non-OpenAI-compatible base_url",
            extra={"base_url": provider_cfg.base_url},
        )
        return self._manual_replay_decision()
    return decision


@staticmethod
def _supports_openai_response_replay(base_url: str | None) -> bool:
    if not isinstance(base_url, str) or not base_url.strip():
        return False
    try:
        parsed = urlparse(base_url.strip())
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False
    if hostname == "api.openai.com":
        return True
    if hostname.endswith(".openai.azure.com"):
        return True
    return False


def _requires_assistant_response_id_for_replay(self) -> bool:
    return self._resolve_replay_decision().require_assistant_response_id


def _sanitize_history_for_replay(
    self,
    history: list[AnyMessage],
    *,
    require_assistant_response_id: bool,
) -> list[AnyMessage]:
    if not history or not require_assistant_response_id:
        return history

    dropped = 0
    kept: list[AnyMessage] = []
    for msg in history:
        if isinstance(msg, AIMessage) and extract_response_id(msg) is None:
            dropped += 1
            continue
        kept.append(msg)

    if dropped:
        logger.warning(
            "Dropped assistant history without response_id for Responses replay safety",
            extra={"dropped_messages": dropped},
        )
    return kept


@staticmethod
def _drop_trailing_user_message(
    history: list[AnyMessage],
    *,
    user_content: str,
) -> list[AnyMessage]:
    if not history:
        return history
    last = history[-1]
    if not isinstance(last, HumanMessage):
        return history
    if last.content != user_content:
        return history
    return history[:-1]


def _build_context_metrics(self, messages: list[object]) -> dict[str, dict]:
    total_tokens = 0
    total_chars = 0
    for msg in messages:
        text = self._message_text_for_metrics(msg)
        total_tokens += count_tokens_approximately(text)
        total_chars += len(text)

    history_usage = {
        "tokens": total_tokens,
        "chars": total_chars,
        "messages": len(messages),
    }
    history_truncation = {
        "truncated": False,
        "dropped_messages": 0,
        "dropped_tokens": 0,
    }
    return self._context_builder.build_metrics(
        history_usage={"history": history_usage},
        history_truncation={"history": history_truncation},
    )
