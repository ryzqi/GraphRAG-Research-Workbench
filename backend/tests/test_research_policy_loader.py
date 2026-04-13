from __future__ import annotations

from pathlib import Path

import pytest

from app.config.policy_loader import load_research_policy
from app.config.policy_provider import StaticFilePolicyProvider


def _policy_base_path() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "app" / "config" / "policies"


def test_research_policy_loader_reads_versioned_yaml() -> None:
    provider = StaticFilePolicyProvider(base_path=_policy_base_path())

    policy = load_research_policy(provider=provider)

    assert policy.coverage_gate.default_required_web_providers == (
        "tavily",
        "searxng",
        "jina_reader",
    )
    assert policy.coverage_gate.required_web_provider_counts["simple"] == 2
    assert policy.coverage_gate.required_web_provider_counts["comparative"] == 3
    assert policy.coverage_gate.required_unique_source_counts["complex"] == 12
    assert policy.status_probe.cache_ttl_seconds == pytest.approx(300.0)
    assert policy.status_probe.search_probe_query == "web search health check"
    assert policy.status_probe.jina_probe_url == "https://example.com"
