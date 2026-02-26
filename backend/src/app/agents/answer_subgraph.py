"""Answer subgraph entrypoint wrapper for KB Chat v3 rollout."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.agents.kb_chat_agentic.answer_subgraph import build_answer_subgraph as _build
from app.core.settings import Settings


def build_answer_subgraph(*, settings: Settings, chat_model: ChatOpenAI):
    """Compile the existing answer subgraph through a stable entrypoint."""

    return _build(settings=settings, chat_model=chat_model)

