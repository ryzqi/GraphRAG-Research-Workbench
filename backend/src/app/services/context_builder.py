"""上下文构建器：统一裁剪、预算与指标产出。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.settings import Settings, get_settings
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.services.retrieval_service import RetrievalResult
from app.utils.token_counter import count_tokens_approximately


@dataclass(slots=True)
class ContextBuildResult:
    """上下文构建结果。"""

    messages: list[LLMMessage]
    budgets: dict[str, int | None]
    usage: dict[str, dict[str, int]]
    truncation: dict[str, dict[str, int | bool]]
    retrieval_context: str | None = None
    tool_context: str | None = None
    included_retrieval: list[RetrievalResult] = field(default_factory=list)


class ContextBuilder:
    """统一上下文裁剪与指标产出。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def build_history_messages(
        self,
        *,
        history: list[LLMMessage],
        summary_text: str | None,
    ) -> tuple[
        list[LLMMessage], dict[str, dict[str, int]], dict[str, dict[str, int | bool]]
    ]:
        summary_usage = {"tokens": 0, "chars": 0}
        summary_truncation = {"truncated": False, "dropped_tokens": 0}
        summary_message: LLMMessage | None = None

        if summary_text:
            summary_content, summary_tokens, truncated = self._truncate_text(
                summary_text, self._normalize_budget(self._settings.summary_max_tokens)
            )
            if truncated:
                summary_truncation = {
                    "truncated": True,
                    "dropped_tokens": max(
                        count_tokens_approximately(summary_text) - summary_tokens, 0
                    ),
                }
            summary_usage = {"tokens": summary_tokens, "chars": len(summary_content)}
            summary_message = LLMMessage(
                role="system", content=f"对话摘要：\n{summary_content}"
            )

        history_messages, history_usage, history_truncation = self._truncate_history(
            history,
            max_messages=self._normalize_budget(
                self._settings.context_history_max_messages
            ),
            max_tokens=self._normalize_budget(
                self._settings.context_history_max_tokens
            ),
        )

        messages = [summary_message] if summary_message else []
        messages.extend(history_messages)

        usage = {
            "summary": summary_usage,
            "history": history_usage,
        }
        truncation = {
            "summary": summary_truncation,
            "history": history_truncation,
        }
        return messages, usage, truncation

    def build_retrieval_context(
        self, results: list[RetrievalResult]
    ) -> tuple[str, list[RetrievalResult], dict[str, int], dict[str, int | bool]]:
        if not results:
            return (
                "（未找到相关内容）",
                [],
                {"tokens": 0, "chars": 0, "items": 0},
                {
                    "truncated": False,
                    "dropped_items": 0,
                    "dropped_tokens": 0,
                },
            )

        included: list[RetrievalResult] = []
        used_tokens = 0
        chunk_tokens_list = [self._chunk_tokens(result) for result in results]
        total_tokens = sum(chunk_tokens_list)
        max_tokens = self._normalize_budget(
            self._settings.context_retrieval_max_tokens
        )
        truncated_text_by_index: dict[int, str] = {}
        text_truncated = False

        for index, (r, chunk_tokens) in enumerate(
            zip(results, chunk_tokens_list, strict=False)
        ):
            if max_tokens is not None and used_tokens + chunk_tokens > max_tokens:
                if not included:
                    truncated_text, truncated_tokens, truncated = self._truncate_text(
                        self._result_text(r),
                        max_tokens,
                    )
                    included.append(r)
                    truncated_text_by_index[index] = truncated_text
                    used_tokens = truncated_tokens
                    text_truncated = truncated
                break
            included.append(r)
            used_tokens += chunk_tokens

        if not included:
            context = "（检索结果被预算裁剪）"
        else:
            context_parts: list[str] = []
            for i, r in enumerate(included, 1):
                text = truncated_text_by_index.get(i - 1, self._result_text(r))
                label = self._result_citation_label(r, index=i)
                context_parts.append(f"[{label}] {text}")
            context = "\n\n".join(context_parts)

        usage = {
            "tokens": used_tokens,
            "chars": len(context),
            "items": len(included),
        }
        truncation = {
            "truncated": len(included) < len(results) or text_truncated,
            "dropped_items": max(len(results) - len(included), 0),
            "dropped_tokens": max(total_tokens - used_tokens, 0),
        }
        return context, included, usage, truncation

    @staticmethod
    def _result_citation_label(result: RetrievalResult, *, index: int) -> str:
        del result
        return f"S{index}"

    def build_tool_context(
        self, tool_results: list[dict]
    ) -> tuple[str, dict[str, int], dict[str, int | bool]]:
        if not tool_results:
            return (
                "",
                {"tokens": 0, "chars": 0, "items": 0},
                {
                    "truncated": False,
                    "dropped_items": 0,
                    "dropped_tokens": 0,
                },
            )

        max_tokens = self._normalize_budget(self._settings.context_tool_max_tokens)
        included: list[str] = []
        used_tokens = 0
        total_tokens = 0
        text_truncated = False

        for r in tool_results:
            line = (
                f"- {r['tool_name']} ({r['extension_name']}): "
                f"{'成功' if r['success'] else '失败'} - {r['output']}"
            )
            line_tokens = count_tokens_approximately(line)
            total_tokens += line_tokens
            if max_tokens is not None and used_tokens + line_tokens > max_tokens:
                if not included:
                    truncated_text, truncated_tokens, truncated = self._truncate_text(
                        line, max_tokens
                    )
                    included.append(truncated_text)
                    used_tokens = truncated_tokens
                    text_truncated = truncated
                break
            included.append(line)
            used_tokens += line_tokens

        context = "\n".join(included)
        usage = {"tokens": used_tokens, "chars": len(context), "items": len(included)}
        truncation = {
            "truncated": len(included) < len(tool_results) or text_truncated,
            "dropped_items": max(len(tool_results) - len(included), 0),
            "dropped_tokens": max(total_tokens - used_tokens, 0),
        }
        return context, usage, truncation

    def build_messages(
        self,
        *,
        system_prompt: str,
        history_messages: list[LLMMessage],
        question: str,
    ) -> list[LLMMessage]:
        return [
            LLMMessage(role="system", content=system_prompt),
            *history_messages,
            LLMMessage(role="user", content=question),
        ]

    def build_metrics(
        self,
        *,
        history_usage: dict[str, dict[str, int]],
        history_truncation: dict[str, dict[str, int | bool]],
        retrieval_usage: dict[str, int] | None = None,
        retrieval_truncation: dict[str, int | bool] | None = None,
        tool_usage: dict[str, int] | None = None,
        tool_truncation: dict[str, int | bool] | None = None,
    ) -> dict[str, dict]:
        usage: dict[str, dict[str, int]] = {
            "summary": {"tokens": 0, "chars": 0},
            "history": {"tokens": 0, "chars": 0, "messages": 0},
            **history_usage,
            "retrieval": retrieval_usage or {"tokens": 0, "chars": 0, "items": 0},
            "tools": tool_usage or {"tokens": 0, "chars": 0, "items": 0},
        }

        total_tokens = sum(part.get("tokens", 0) for part in usage.values())
        total_chars = sum(part.get("chars", 0) for part in usage.values())
        usage["total"] = {"tokens": total_tokens, "chars": total_chars}

        truncation: dict[str, dict[str, int | bool]] = {
            "summary": {"truncated": False, "dropped_tokens": 0},
            "history": {
                "truncated": False,
                "dropped_messages": 0,
                "dropped_tokens": 0,
            },
            **history_truncation,
            "retrieval": retrieval_truncation
            or {"truncated": False, "dropped_items": 0, "dropped_tokens": 0},
            "tools": tool_truncation
            or {"truncated": False, "dropped_items": 0, "dropped_tokens": 0},
        }

        budgets = {
            "llm_input_tokens": self._normalize_budget(
                self._settings.llm_max_input_tokens
            ),
            "history_messages": self._normalize_budget(
                self._settings.context_history_max_messages
            ),
            "history_tokens": self._normalize_budget(
                self._settings.context_history_max_tokens
            ),
            "retrieval_tokens": self._normalize_budget(
                self._settings.context_retrieval_max_tokens
            ),
            "summary_tokens": self._normalize_budget(self._settings.summary_max_tokens),
            "tool_tokens": self._normalize_budget(
                self._settings.context_tool_max_tokens
            ),
        }

        derived = {
            "context_utilization": {
                "llm_input_tokens": self._safe_ratio(
                    total_tokens,
                    budgets["llm_input_tokens"],
                ),
                "history_tokens": self._safe_ratio(
                    usage["history"].get("tokens", 0),
                    budgets["history_tokens"],
                ),
                "retrieval_tokens": self._safe_ratio(
                    usage["retrieval"].get("tokens", 0),
                    budgets["retrieval_tokens"],
                ),
                "tool_tokens": self._safe_ratio(
                    usage["tools"].get("tokens", 0),
                    budgets["tool_tokens"],
                ),
                "summary_tokens": self._safe_ratio(
                    usage["summary"].get("tokens", 0),
                    budgets["summary_tokens"],
                ),
            },
            "truncation_rate": {
                "history": self._safe_ratio(
                    int(truncation["history"].get("dropped_tokens", 0) or 0),
                    (
                        usage["history"].get("tokens", 0)
                        + int(truncation["history"].get("dropped_tokens", 0) or 0)
                    ),
                ),
                "retrieval": self._safe_ratio(
                    int(truncation["retrieval"].get("dropped_tokens", 0) or 0),
                    (
                        usage["retrieval"].get("tokens", 0)
                        + int(truncation["retrieval"].get("dropped_tokens", 0) or 0)
                    ),
                ),
                "tools": self._safe_ratio(
                    int(truncation["tools"].get("dropped_tokens", 0) or 0),
                    (
                        usage["tools"].get("tokens", 0)
                        + int(truncation["tools"].get("dropped_tokens", 0) or 0)
                    ),
                ),
                "summary": self._safe_ratio(
                    int(truncation["summary"].get("dropped_tokens", 0) or 0),
                    (
                        usage["summary"].get("tokens", 0)
                        + int(truncation["summary"].get("dropped_tokens", 0) or 0)
                    ),
                ),
            },
            "overall_truncated": any(
                bool(part.get("truncated"))
                for part in truncation.values()
            ),
        }

        return {
            "budgets": budgets,
            "usage": usage,
            "truncation": truncation,
            "derived": derived,
        }

    @staticmethod
    def _normalize_budget(value: int | None) -> int | None:
        if value is None:
            return None
        return value if value > 0 else None

    @staticmethod
    def _safe_ratio(
        numerator: int | float | None,
        denominator: int | float | None,
    ) -> float | None:
        if numerator is None or denominator is None:
            return None
        try:
            normalized_denominator = float(denominator)
            normalized_numerator = float(numerator)
        except (TypeError, ValueError):
            return None
        if normalized_denominator <= 0:
            return None
        return round(normalized_numerator / normalized_denominator, 4)

    @staticmethod
    def _truncate_text(text: str, max_tokens: int | None) -> tuple[str, int, bool]:
        if max_tokens is None:
            return text, count_tokens_approximately(text), False
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text, count_tokens_approximately(text), False
        truncated_text = text[: max(max_chars - 1, 0)].rstrip()
        if truncated_text != text:
            truncated_text = f"{truncated_text}…"
        return truncated_text, count_tokens_approximately(truncated_text), True

    def _truncate_history(
        self,
        history: list[LLMMessage],
        *,
        max_messages: int | None,
        max_tokens: int | None,
    ) -> tuple[list[LLMMessage], dict[str, int], dict[str, int | bool]]:
        if not history:
            return (
                [],
                {"tokens": 0, "chars": 0, "messages": 0},
                {
                    "truncated": False,
                    "dropped_messages": 0,
                    "dropped_tokens": 0,
                },
            )

        history_token_counts = [
            count_tokens_approximately(message.content) for message in history
        ]
        total_tokens = sum(history_token_counts)

        kept: list[LLMMessage] = []
        used_tokens = 0

        for msg, msg_tokens in zip(
            reversed(history),
            reversed(history_token_counts),
            strict=False,
        ):
            if max_tokens is not None and used_tokens + msg_tokens > max_tokens:
                break
            kept.append(msg)
            used_tokens += msg_tokens
            if max_messages is not None and len(kept) >= max_messages:
                break

        kept.reverse()
        usage = {
            "tokens": used_tokens,
            "chars": sum(len(m.content) for m in kept),
            "messages": len(kept),
        }
        truncation = {
            "truncated": len(kept) < len(history),
            "dropped_messages": max(len(history) - len(kept), 0),
            "dropped_tokens": max(total_tokens - used_tokens, 0),
        }
        return kept, usage, truncation

    @staticmethod
    def _chunk_tokens(result: RetrievalResult) -> int:
        text = ContextBuilder._result_text(result)
        return count_tokens_approximately(text)

    @staticmethod
    def _result_text(result: RetrievalResult) -> str:
        if result.context_text:
            return result.context_text
        return result.chunk.content
