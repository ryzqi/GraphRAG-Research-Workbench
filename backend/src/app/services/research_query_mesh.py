"""Research query mesh helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchPlanSnapshot, ResearchSourceTarget

ResearchComplexityLiteral = Literal["simple", "comparative", "complex"]
DEFAULT_REQUIRED_WEB_PROVIDERS = ("tavily", "jina_reader", "searxng")

_REQUIRED_WEB_PROVIDER_COUNTS: dict[ResearchComplexityLiteral, int] = {
    "simple": 2,
    "comparative": 3,
    "complex": 3,
}
_REQUIRED_UNIQUE_SOURCE_COUNTS: dict[ResearchComplexityLiteral, int] = {
    "simple": 5,
    "comparative": 8,
    "complex": 12,
}


@dataclass(slots=True, frozen=True)
class ResearchQueryMesh:
    canonical_query: str
    breadth_queries: tuple[str, ...]
    depth_queries: tuple[str, ...]
    verification_queries: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class CoverageGateResult:
    passed: bool
    reasons: tuple[str, ...]


def build_research_query_mesh(*, question: str, plan_snapshot: ResearchPlanSnapshot) -> ResearchQueryMesh:
    canonical_query = str(question).strip()
    if not canonical_query:
        raise ValueError("question 不能为空")

    prompts = get_prompt_loader()
    breadth_queries = _unique_queries(
        [
            canonical_query,
            prompts.render(
                "research/query_mesh_breadth_compare",
                canonical_query=canonical_query,
            ),
            plan_snapshot.research_brief,
        ]
    )
    depth_queries = _unique_queries(
        [
            prompts.render(
                "research/query_mesh_depth_subtask_evidence",
                subtask_title=item.title,
            )
            for item in plan_snapshot.subtasks
        ]
        or [
            prompts.render(
                "research/query_mesh_depth_fallback",
                canonical_query=canonical_query,
            )
        ]
    )
    verification_queries = _unique_queries(
        [
            prompts.render(
                "research/query_mesh_verification_crosscheck",
                canonical_query=canonical_query,
            ),
            prompts.render(
                "research/query_mesh_verification_risks",
                canonical_query=canonical_query,
            ),
            *(
                prompts.render(
                    "research/query_mesh_subtask_verification",
                    subtask_title=item.title,
                )
                for item in plan_snapshot.subtasks
            ),
        ]
    )
    return ResearchQueryMesh(
        canonical_query=canonical_query,
        breadth_queries=breadth_queries,
        depth_queries=depth_queries,
        verification_queries=verification_queries,
    )


def evaluate_coverage_gate(
    *,
    complexity: ResearchComplexityLiteral,
    provider_counts: dict[str, int],
    unique_source_count: int,
    source_types: set[str],
    target_sources: set[ResearchSourceTarget],
) -> CoverageGateResult:
    required_sources = _REQUIRED_UNIQUE_SOURCE_COUNTS[complexity]
    reasons: list[str] = []
    target_source_values = {item.value for item in target_sources}
    workspace_only_web_evidence = _is_workspace_only_web_evidence(
        provider_counts=provider_counts,
        source_types=source_types,
        target_sources=target_sources,
    )
    available_web_provider_count = len(
        [
            name
            for name, count in provider_counts.items()
            if count > 0 and name in DEFAULT_REQUIRED_WEB_PROVIDERS
        ]
    )
    if (
        ResearchSourceTarget.WEB.value in target_source_values
        and not workspace_only_web_evidence
        and available_web_provider_count < _REQUIRED_WEB_PROVIDER_COUNTS[complexity]
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
    normalized_available = _unique_queries(available_providers)
    required_count = _REQUIRED_WEB_PROVIDER_COUNTS[complexity]
    required: list[str] = list(DEFAULT_REQUIRED_WEB_PROVIDERS[:required_count])
    for provider in normalized_available:
        if provider in required:
            continue
        required.append(provider)
    return tuple(required)


def _unique_queries(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def _is_workspace_only_web_evidence(
    *,
    provider_counts: dict[str, int],
    source_types: set[str],
    target_sources: set[ResearchSourceTarget],
) -> bool:
    if ResearchSourceTarget.WEB not in target_sources or "web" not in source_types:
        return False
    nonzero_providers = {name for name, count in provider_counts.items() if count > 0}
    return nonzero_providers == {"workspace"}
