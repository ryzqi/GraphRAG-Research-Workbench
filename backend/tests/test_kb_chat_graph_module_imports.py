"""KB Chat 图相关模块的导入烟雾测试。"""

from __future__ import annotations

import importlib

import pytest


_KB_CHAT_GRAPH_MODULES = (
    "app.agents.kb_chat_agentic.answer_subgraph",
    "app.agents.kb_chat_agentic.answer_subgraph_finalize",
    "app.agents.kb_chat_agentic.answer_subgraph_review_ops",
    "app.agents.kb_chat_agentic_graph",
    "app.agents.preprocess_subgraph",
    "app.agents.retrieval_subgraph",
)


@pytest.mark.parametrize("module_name", _KB_CHAT_GRAPH_MODULES)
def test_kb_chat_graph_modules_import_cleanly(module_name: str) -> None:
    importlib.import_module(module_name)
