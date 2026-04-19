"""Research query mesh helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from app.config.policy_loader import load_research_policy
from app.prompts import get_prompt_loader
from app.schemas.research import ResearchPlanSnapshot, ResearchSourceTarget

ResearchComplexityLiteral = Literal["simple", "comparative", "complex"]


@dataclass(slots=True, frozen=True)
class ResearchQueryMesh:
    canonical_query: str
    breadth_queries: tuple[str, ...]
    depth_queries: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class CoverageGateResult:
    passed: bool
    reasons: tuple[str, ...]


def build_research_query_mesh(
    *, question: str, plan_snapshot: ResearchPlanSnapshot
) -> ResearchQueryMesh:
    canonical_query = str(question).strip()
    if not canonical_query:
        raise ValueError("question 不能为空")

    prompts = get_prompt_loader()
    breadth_queries = _unique(
        [
            canonical_query,
            prompts.render(
                "research/query_mesh_breadth",
                canonical_query=canonical_query,
            ),
            plan_snapshot.research_brief,
        ]
    )
    depth_queries = _unique(
        [
            prompts.render(
                "research/query_mesh_depth",
                canonical_query=canonical_query,
                subtask_title=item.title,
            )
            for item in plan_snapshot.subtasks
        ]
        or [
            prompts.render(
                "research/query_mesh_depth",
                canonical_query=canonical_query,
                subtask_title="主线",
            )
        ]
    )
    return ResearchQueryMesh(
        canonical_query=canonical_query,
        breadth_queries=breadth_queries,
        depth_queries=depth_queries,
    )


def evaluate_coverage_gate(
    *,
    complexity: ResearchComplexityLiteral,
    provider_counts: dict[str, int],
    unique_source_count: int,
    source_types: set[str],
    target_sources: set[ResearchSourceTarget],
) -> CoverageGateResult:
    coverage_policy = load_research_policy().coverage_gate
    required_sources = coverage_policy.required_unique_source_counts[complexity]
    reasons: list[str] = []
    target_source_values = {item.value for item in target_sources}
    workspace_only_web_evidence = _workspace_only_web(
        provider_counts=provider_counts,
        source_types=source_types,
        target_sources=target_sources,
    )
    available_web_provider_count = len(
        [
            name
            for name, count in provider_counts.items()
            if count > 0 and name in coverage_policy.default_required_web_providers
        ]
    )
    if (
        ResearchSourceTarget.WEB.value in target_source_values
        and not workspace_only_web_evidence
        and available_web_provider_count
        < coverage_policy.required_web_provider_counts[complexity]
    ):
        reasons.append("missing_web_provider_count")
    if unique_source_count < required_sources:
        reasons.append("unique_source_count_low")
    if (
        ResearchSourceTarget.PAPER.value in target_source_values
        and "paper" not in source_types
    ):
        reasons.append("paper_source_missing")
    return CoverageGateResult(
        passed=not reasons,
        reasons=tuple(reasons),
    )


def select_required_web_providers(
    *,
    complexity: ResearchComplexityLiteral,
    available_providers: Iterable[str],
) -> tuple[str, ...]:
    coverage_policy = load_research_policy().coverage_gate
    normalized_available = _unique(available_providers)
    required_count = coverage_policy.required_web_provider_counts[complexity]
    required: list[str] = list(
        coverage_policy.default_required_web_providers[:required_count]
    )
    for provider in normalized_available:
        if provider in required:
            continue
        required.append(provider)
    return tuple(required)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = str(item or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return tuple(deduped)


def _workspace_only_web(
    *,
    provider_counts: dict[str, int],
    source_types: set[str],
    target_sources: set[ResearchSourceTarget],
) -> bool:
    if ResearchSourceTarget.WEB not in target_sources or "web" not in source_types:
        return False
    nonzero_providers = {name for name, count in provider_counts.items() if count > 0}
    return nonzero_providers == {"workspace"}
