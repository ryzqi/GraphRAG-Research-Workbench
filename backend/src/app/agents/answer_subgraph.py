"""Answer subgraph entrypoint wrapper for KB Chat v3 rollout."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.kb_chat_agentic.answer_subgraph import build_answer_subgraph as _build
from app.core.settings import Settings


def build_answer_subgraph(*, settings: Settings, chat_model: BaseChatModel):
    """Compile the existing answer subgraph through a stable entrypoint."""

    return _build(settings=settings, chat_model=chat_model)
