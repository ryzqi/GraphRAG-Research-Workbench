"""KB Chat v3 答案子图稳定入口封装。"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.kb_chat_agentic.answer_subgraph import build_answer_subgraph as _build
from app.core.settings import Settings


def build_answer_subgraph(*, settings: Settings, chat_model: BaseChatModel):
    """通过稳定入口编译现有答案子图。"""

    return _build(settings=settings, chat_model=chat_model)
