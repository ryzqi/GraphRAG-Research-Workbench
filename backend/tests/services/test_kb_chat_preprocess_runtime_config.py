from __future__ import annotations

from types import SimpleNamespace

from app.agents.kb_chat_agentic.preprocess import (
    decomp_check_route,
    hyde_check_route,
    multi_query_check_route,
)


def _settings_stub(*, decomp: bool = False, multi: bool = False, hyde: bool = False):
    return SimpleNamespace(
        kb_chat_decomposition_enabled=decomp,
        kb_chat_multi_query_enabled=multi,
        kb_chat_hyde_enabled=hyde,
    )


def test_decomp_check_route_prefers_runtime_override() -> None:
    settings = _settings_stub(decomp=False)
    state = {"runtime_config": {"decomposition_enabled": True}}

    assert decomp_check_route(state, settings) == "decomposition"


def test_multi_query_check_route_prefers_runtime_override() -> None:
    settings = _settings_stub(multi=False)
    state = {"runtime_config": {"multi_query_enabled": True}}

    assert multi_query_check_route(state, settings) == "generate_variants"


def test_hyde_check_route_prefers_runtime_override() -> None:
    settings = _settings_stub(hyde=False)
    state = {"runtime_config": {"hyde_enabled": True}}

    assert hyde_check_route(state, settings) == "hyde"
