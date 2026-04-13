from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

from app.config.policy_models import FrontendRuntimePolicy, ResearchPolicy, SearchPolicy
from app.config.policy_provider import PolicyProvider, StaticFilePolicyProvider

PolicyModelT = TypeVar("PolicyModelT", bound=BaseModel)


def _load_policy(
    *,
    policy_name: str,
    model_type: type[PolicyModelT],
    provider: PolicyProvider,
) -> PolicyModelT:
    payload = provider.load_policy_data(policy_name)
    return model_type.model_validate(payload)


@lru_cache
def _default_policy_provider() -> StaticFilePolicyProvider:
    return StaticFilePolicyProvider()


@lru_cache
def _load_default_search_policy() -> SearchPolicy:
    return _load_policy(
        policy_name="search_policy",
        model_type=SearchPolicy,
        provider=_default_policy_provider(),
    )


@lru_cache
def _load_default_research_policy() -> ResearchPolicy:
    return _load_policy(
        policy_name="research_policy",
        model_type=ResearchPolicy,
        provider=_default_policy_provider(),
    )


@lru_cache
def _load_default_frontend_runtime_policy() -> FrontendRuntimePolicy:
    return _load_policy(
        policy_name="frontend_runtime_policy",
        model_type=FrontendRuntimePolicy,
        provider=_default_policy_provider(),
    )


def load_search_policy(*, provider: PolicyProvider | None = None) -> SearchPolicy:
    if provider is None:
        return _load_default_search_policy()
    return _load_policy(
        policy_name="search_policy",
        model_type=SearchPolicy,
        provider=provider,
    )


def load_research_policy(*, provider: PolicyProvider | None = None) -> ResearchPolicy:
    if provider is None:
        return _load_default_research_policy()
    return _load_policy(
        policy_name="research_policy",
        model_type=ResearchPolicy,
        provider=provider,
    )


def load_frontend_runtime_policy(
    *,
    provider: PolicyProvider | None = None,
) -> FrontendRuntimePolicy:
    if provider is None:
        return _load_default_frontend_runtime_policy()
    return _load_policy(
        policy_name="frontend_runtime_policy",
        model_type=FrontendRuntimePolicy,
        provider=provider,
    )
