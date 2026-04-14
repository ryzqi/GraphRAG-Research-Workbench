from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

from langchain.messages import AIMessage, HumanMessage

from app.integrations.llm_client import ChatMessage as LLMMessage
from app.utils.text_sanitization import sanitize_visible_text


class ContextSeedTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class KbChatContextSeed(TypedDict):
    summary_text: str
    recent_turns: list[ContextSeedTurn]
    question: str


def _normalize_text(value: object) -> str:
    return sanitize_visible_text(str(value or "")).strip()


def _normalize_role(value: object) -> Literal["user", "assistant"] | None:
    role = str(value or "").strip().lower()
    if role == "user":
        return "user"
    if role == "assistant":
        return "assistant"
    return None


def _coerce_turns(turns: Sequence[Mapping[str, object]]) -> list[ContextSeedTurn]:
    normalized: list[ContextSeedTurn] = []
    for turn in turns:
        role = _normalize_role(turn.get("role"))
        if role is None:
            continue
        content = _normalize_text(turn.get("content") or turn.get("text"))
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def context_seed_turns_from_history(
    history: Sequence[LLMMessage],
) -> list[ContextSeedTurn]:
    turns: list[ContextSeedTurn] = []
    for message in history:
        role = _normalize_role(getattr(message, "role", None))
        if role is None:
            continue
        content = _normalize_text(getattr(message, "content", None))
        if not content:
            continue
        turns.append({"role": role, "content": content})
    return turns


def context_seed_turns_from_messages(
    messages: Sequence[Any],
) -> list[ContextSeedTurn]:
    turns: list[ContextSeedTurn] = []
    for message in messages:
        role: Literal["user", "assistant"] | None = None
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        if role is None:
            continue
        content = _normalize_text(getattr(message, "content", None))
        if not content:
            continue
        turns.append({"role": role, "content": content})
    return turns


def build_context_seed(
    *,
    summary_text: str | None,
    turns: Sequence[Mapping[str, object]],
    question: str,
    max_turns: int,
    exclude_question: str | None = None,
    exclude_answer: str | None = None,
) -> KbChatContextSeed:
    normalized_turns = _coerce_turns(turns)
    normalized_question = _normalize_text(question)
    normalized_excluded_question = _normalize_text(exclude_question)
    normalized_answer = _normalize_text(exclude_answer)

    if normalized_answer and normalized_turns:
        last_turn = normalized_turns[-1]
        if (
            last_turn["role"] == "assistant"
            and last_turn["content"] == normalized_answer
        ):
            normalized_turns.pop()

    if normalized_excluded_question and normalized_turns:
        last_turn = normalized_turns[-1]
        if (
            last_turn["role"] == "user"
            and last_turn["content"] == normalized_excluded_question
        ):
            normalized_turns.pop()

    max_items = max(0, int(max_turns)) * 2
    if max_items > 0 and len(normalized_turns) > max_items:
        normalized_turns = normalized_turns[-max_items:]

    return {
        "summary_text": _normalize_text(summary_text),
        "recent_turns": normalized_turns,
        "question": normalized_question,
    }


def build_context_seed_from_history(
    *,
    summary_text: str | None,
    history: Sequence[LLMMessage],
    question: str,
    max_turns: int,
    current_answer: str | None = None,
    exclude_question: str | None = None,
) -> KbChatContextSeed:
    return build_context_seed(
        summary_text=summary_text,
        turns=context_seed_turns_from_history(history),
        question=question,
        max_turns=max_turns,
        exclude_question=(
            exclude_question if exclude_question is not None else question
            if current_answer is not None
            else None
        ),
        exclude_answer=current_answer,
    )


def build_context_seed_from_messages(
    *,
    summary_text: str | None,
    messages: Sequence[Any],
    question: str,
    max_turns: int,
    exclude_question: str | None = None,
    exclude_answer: str | None = None,
) -> KbChatContextSeed:
    return build_context_seed(
        summary_text=summary_text,
        turns=context_seed_turns_from_messages(messages),
        question=question,
        max_turns=max_turns,
        exclude_question=exclude_question,
        exclude_answer=exclude_answer,
    )


def context_seed_turns_to_context_frame_turns(
    turns: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    context_turns: list[dict[str, str]] = []
    for turn in _coerce_turns(turns):
        context_turns.append({"role": turn["role"], "text": turn["content"]})
    return context_turns
