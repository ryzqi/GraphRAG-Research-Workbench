"""普通聊天网页搜索主流水线。"""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Any

from langchain_core.documents import Document

from .contracts import ReadProvider, SearchRetriever
from .documents import document_to_result
from .enrichment import enrich_documents
from .fusion import fuse_documents
from .query_rewrite import build_search_query_plan
from .rerank import rerank_documents


class WebSearchPipeline:
    """LangChain 风格的查询改写 -> 多 retriever -> 融合 -> 补读 -> 重排流水线。"""

    def __init__(
        self,
        *,
        retrievers: list[SearchRetriever],
        read_provider: ReadProvider | None = None,
    ) -> None:
        self._retrievers = list(retrievers)
        self._read_provider = read_provider

    async def search(
        self,
        *,
        query: str,
        max_results: int = 5,
        search_type: str | None = None,
        search_depth: str | None = None,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        include_raw_content: bool | str | None = None,
        include_answer: bool | str | None = None,
        include_images: bool | None = None,
        include_image_descriptions: bool | None = None,
        include_favicon: bool | None = None,
        include_usage: bool | None = None,
        auto_parameters: bool | None = None,
        timeout_seconds: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        start = perf_counter()
        query_plan = build_search_query_plan(
            query,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        if not self._retrievers:
            return {
                "query": query,
                "query_plan": {
                    "original_query": query_plan.original_query,
                    "rewritten_queries": query_plan.rewritten_queries,
                },
                "results": [],
                "provider_reports": [],
                "merged_count": 0,
                "elapsed_ms": int((perf_counter() - start) * 1000),
                "error": {"message": "未配置可用的 Web 搜索 provider"},
                "cache_hit": False,
            }
        provider_reports: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "provider": "",
                "ok": False,
                "result_count": 0,
                "elapsed_ms": 0,
                "error": None,
            }
        )
        collected_groups: list[list[Document]] = []

        for rewritten_query in query_plan.rewritten_queries:
            for retriever in self._retrievers:
                provider_start = perf_counter()
                provider_reports[retriever.provider_name]["provider"] = retriever.provider_name
                try:
                    documents = await retriever.aretrieve(
                        rewritten_query,
                        max_results=max(max_results * 2, max_results),
                        search_type=search_type,
                        search_depth=search_depth,
                        time_range=time_range,
                        include_domains=include_domains,
                        exclude_domains=exclude_domains,
                        include_raw_content=include_raw_content,
                        include_answer=include_answer,
                        include_images=include_images,
                        include_image_descriptions=include_image_descriptions,
                        include_favicon=include_favicon,
                        include_usage=include_usage,
                        auto_parameters=auto_parameters,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:
                    if provider_reports[retriever.provider_name]["error"] is None:
                        provider_reports[retriever.provider_name]["error"] = str(exc)
                    provider_reports[retriever.provider_name]["elapsed_ms"] += int((perf_counter() - provider_start) * 1000)
                    continue
                provider_reports[retriever.provider_name]["ok"] = True
                provider_reports[retriever.provider_name]["error"] = None
                provider_reports[retriever.provider_name]["result_count"] += len(documents)
                provider_reports[retriever.provider_name]["elapsed_ms"] += int((perf_counter() - provider_start) * 1000)
                collected_groups.append(documents)

        fused = fuse_documents(collected_groups, max_results=max(max_results * 3, max_results))
        enriched, enrichment_report = await enrich_documents(
            fused,
            read_provider=self._read_provider,
            top_k=2,
            timeout_seconds=timeout_seconds,
        )
        reranked = rerank_documents(enriched, query=query, max_results=max_results)
        reports = list(provider_reports.values())
        if enrichment_report is not None:
            reports.append(enrichment_report)

        return {
            "query": query,
            "query_plan": {
                "original_query": query_plan.original_query,
                "rewritten_queries": query_plan.rewritten_queries,
            },
            "results": [document_to_result(document) for document in reranked],
            "provider_reports": reports,
            "merged_count": len(reranked),
            "elapsed_ms": int((perf_counter() - start) * 1000),
            "error": None,
            "cache_hit": False,
        }
