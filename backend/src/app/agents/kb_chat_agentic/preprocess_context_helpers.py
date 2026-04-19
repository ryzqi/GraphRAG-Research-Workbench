"""KB Chat preprocess 上下文整理辅助。"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from typing import Any, cast

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from app.core.settings import Settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.services.kb_chat_context_seed import (
    build_context_seed_from_messages,
    context_seed_turns_to_context_frame_turns,
)
from app.utils.token_counter import count_tokens_approximately

from .preprocess_query_bundle import _as_dict

def _latest_summary_message(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, SystemMessage):
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.startswith("对话摘要："):
                return content
    return ""


def _strip_summary_prefix(summary: str) -> str:
    text = summary.strip()
    if text.startswith("对话摘要："):
        text = text[len("对话摘要：") :].strip()
    return text


def _recent_dialogue(messages: list[Any], *, max_turns: int = 3) -> str:
    """没有显式摘要时使用的对话上下文兜底。"""
    lines: list[str] = []
    for msg in reversed(messages):
        role = None
        if isinstance(msg, HumanMessage):
            role = "用户"
        elif isinstance(msg, AIMessage):
            role = "助手"
        else:
            continue
        content = getattr(msg, "content", "")
        text = content if isinstance(content, str) else str(content)
        text = text.strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
        if len(lines) >= max_turns * 2:
            break
    lines.reverse()
    if not lines:
        return ""
    return "最近对话：\n" + "\n".join(lines)


def _normalize_for_compare(text: str) -> str:
    return " ".join(text.split()).strip()


def _recent_turns(messages: list[Any], *, max_turns: int = 3) -> list[dict[str, str]]:
    seed = build_context_seed_from_messages(
        summary_text="",
        messages=messages,
        question="",
        max_turns=max_turns,
    )
    return context_seed_turns_to_context_frame_turns(seed["recent_turns"])


def _dedupe_turns_preserve_latest(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    if not turns:
        return []
    deduped_reversed: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for turn in reversed(turns):
        role = str(turn.get("role") or "assistant").strip() or "assistant"
        text = str(turn.get("text") or "").strip()
        normalized_text = _normalize_for_compare(text)
        if not normalized_text:
            continue
        key = (role, normalized_text)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append({"role": role, "text": text})
    deduped_reversed.reverse()
    return deduped_reversed


def _render_display_context(
    *,
    summary: str,
    turns: list[dict[str, str]],
    memory_snippet: str,
    question: str,
) -> str:
    parts: list[str] = []
    normalized_question = _normalize_for_compare(question)
    if summary:
        parts.append(summary)
    elif turns:
        lines: list[str] = []
        for turn in turns:
            role = "用户" if turn.get("role") == "user" else "助手"
            text = turn.get("text", "").strip()
            if text:
                if (
                    role == "用户"
                    and _normalize_for_compare(text) == normalized_question
                ):
                    continue
                lines.append(f"{role}: {text}")
        if lines:
            parts.append("最近对话：\n" + "\n".join(lines))
    if memory_snippet:
        parts.append(memory_snippet)
    if normalized_question:
        parts.append(f"用户问题：{question.strip()}")
    return "\n\n".join(part for part in parts if part).strip()


def _turns_to_langchain_messages(turns: list[dict[str, str]]) -> list[Any]:
    lc_messages: list[Any] = []
    for turn in turns:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        if turn.get("role") == "user":
            lc_messages.append(HumanMessage(content=text))
        elif turn.get("role") == "assistant":
            lc_messages.append(AIMessage(content=text))
    return lc_messages


def _extract_summary_text(result: object) -> str:
    running = getattr(result, "running_summary", None)
    if running is not None:
        text = getattr(running, "summary", None) or getattr(running, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

    messages = getattr(result, "messages", None)
    if isinstance(messages, list) and messages:
        first = messages[0]
        content = getattr(first, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


async def _generate_summary_from_turns(
    *, turns: list[dict[str, str]], settings: Settings
) -> str:
    if not turns:
        return ""
    lc_messages = _turns_to_langchain_messages(turns)[-12:]
    if not lc_messages:
        return ""
    try:
        from langmem.short_term import summarize_messages
        from langmem.short_term.summarization import TokenCounter
    except Exception:  # pragma: no cover
        return ""

    try:
        model = create_chat_model(settings=settings)
        summary_model = model.bind(max_tokens=settings.summary_max_tokens)
        token_counter_fn: TokenCounter
        candidate_counter = getattr(model, "get_num_tokens_from_messages", None)
        if callable(candidate_counter):
            token_counter_fn = cast(TokenCounter, candidate_counter)
        else:
            def _fallback_token_counter(msgs: Iterable[Any]) -> int:
                return sum(
                    count_tokens_approximately(getattr(m, "content", "") or "")
                    for m in msgs
                )
            token_counter_fn = _fallback_token_counter
    except Exception:  # pragma: no cover
        return ""

    def _run() -> object:
        return summarize_messages(
            lc_messages,
            running_summary=None,
            token_counter=token_counter_fn,
            model=summary_model,
            max_tokens=settings.summary_max_tokens,
            max_tokens_before_summary=0,
            max_summary_tokens=settings.summary_max_tokens,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception:  # pragma: no cover
        return ""
    return _extract_summary_text(result)


def _select_turns_for_merge(
    turns: list[dict[str, str]], *, question: str, has_summary: bool
) -> list[dict[str, str]]:
    if not turns:
        return []
    normalized_question = _normalize_for_compare(question)
    selected: list[dict[str, str]] = []
    for turn in turns:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        if role == "user" and _normalize_for_compare(text) == normalized_question:
            continue
        selected.append({"role": role or "assistant", "text": text})
    if not selected:
        return []
    max_turns = 2 if has_summary else 4
    return _dedupe_turns_preserve_latest(selected[-max_turns * 2 :])


def _filter_memory_entries_already_covered_by_turns(
    memory: dict[str, Any] | None,
    *,
    question: str,
    turns: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not isinstance(memory, dict):
        return None
    raw_entries = memory.get("entries")
    if not isinstance(raw_entries, list):
        return memory

    normalized_question = _normalize_for_compare(question)
    user_texts = {normalized_question} if normalized_question else set()
    assistant_texts: set[str] = set()
    for turn in turns:
        role = str(turn.get("role") or "assistant").strip().lower()
        normalized_text = _normalize_for_compare(str(turn.get("text") or ""))
        if not normalized_text:
            continue
        if role == "user":
            user_texts.add(normalized_text)
        elif role == "assistant":
            assistant_texts.add(normalized_text)

    filtered_entries: list[Any] = []
    for entry in raw_entries:
        record = _as_dict(entry)
        if not record:
            filtered_entries.append(entry)
            continue
        q = _normalize_for_compare(str(record.get("q") or ""))
        a = _normalize_for_compare(str(record.get("a") or ""))
        if q and a and q in user_texts and a in assistant_texts:
            continue
        filtered_entries.append(record)

    filtered_memory = dict(memory)
    filtered_memory["entries"] = filtered_entries
    return filtered_memory


def _needs_conflict_resolution(*, summary_text: str, memory_snippet: str) -> bool:
    if not summary_text or not memory_snippet:
        return False
    summary_numbers = set(re.findall(r"\d+", summary_text))
    memory_numbers = set(re.findall(r"\d+", memory_snippet))
    return bool(
        summary_numbers
        and memory_numbers
        and summary_numbers.isdisjoint(memory_numbers)
    )
