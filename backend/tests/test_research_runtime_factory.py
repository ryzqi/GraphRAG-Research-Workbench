from __future__ import annotations

from deepagents.backends import CompositeBackend

from app.schemas.research import ResearchSourceTarget
from app.services.research_runtime_factory import (
    build_research_backend,
    resolve_source_subagent_route,
)
from app.services.research_runtime_types import DEFAULT_RESEARCH_BACKEND_POLICY


def test_build_research_backend_routes_persistent_roots_to_store_backend() -> None:
    backend = build_research_backend(DEFAULT_RESEARCH_BACKEND_POLICY)

    assert isinstance(backend, CompositeBackend)
    assert backend.default.__class__.__name__ == 'StateBackend'
    assert backend.routes[DEFAULT_RESEARCH_BACKEND_POLICY.memories_root].__class__.__name__ == 'StoreBackend'
    assert backend.routes[DEFAULT_RESEARCH_BACKEND_POLICY.skills_root].__class__.__name__ == 'StoreBackend'


def test_resolve_source_subagent_route_orders_source_specific_agents_before_citation() -> None:
    route = resolve_source_subagent_route(
        [ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER]
    )

    assert route == ('paper', 'web', 'claim-verifier', 'section-writer', 'citation')
