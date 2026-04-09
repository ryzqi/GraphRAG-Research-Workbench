"""Deep Research source-aware 工具。"""

from __future__ import annotations

import itertools
import json
from typing import Any, Literal

import arxiv
import httpx
from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, Field

from app.agents.tools.web_search import (
    WebCrawlArgs,
    WebExtractArgs,
    WebSearchClient,
)
from app.core.settings import Settings


def _validation_error_output(*, code: str, message: str, **payload: Any) -> str:
    return json.dumps(
        {
            **payload,
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
            },
        },
        ensure_ascii=False,
    )


def build_tavily_extract_tool(
    settings: Settings,
    *,
    redis: Any | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> BaseTool:
    client = WebSearchClient(settings, redis=redis, http_client=http_client)

    async def _extract(**kwargs: object) -> str:
        try:
            args = WebExtractArgs.model_validate(kwargs)
        except Exception:
            return _validation_error_output(
                code="TAVILY_EXTRACT_BAD_REQUEST",
                message="Tavily 抽取参数错误",
                results=[],
            )
        output = await client.extract(args)
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "tavily_extract",
        description="使用 Tavily 抽取指定 URL 的正文与结构化信息。",
        args_schema=WebExtractArgs,
    )(_extract)


def build_tavily_crawl_tool(
    settings: Settings,
    *,
    redis: Any | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> BaseTool:
    client = WebSearchClient(settings, redis=redis, http_client=http_client)

    async def _crawl(**kwargs: object) -> str:
        try:
            args = WebCrawlArgs.model_validate(kwargs)
        except Exception:
            return _validation_error_output(
                code="TAVILY_CRAWL_BAD_REQUEST",
                message="Tavily 爬取参数错误",
                results=[],
            )
        output = await client.crawl(args)
        return json.dumps(output, ensure_ascii=False)

    return lc_tool(
        "tavily_crawl",
        description="使用 Tavily 对站点做受控爬取。",
        args_schema=WebCrawlArgs,
    )(_crawl)


class ArxivSearchArgs(BaseModel):
    query: str = Field(..., description="论文搜索查询")
    max_results: int = Field(default=5, ge=1, le=20)
    sort_by: Literal["relevance", "submitted_date", "last_updated_date"] = Field(
        default="relevance"
    )
    sort_order: Literal["descending", "ascending"] = Field(default="descending")


class ArxivFetchArgs(BaseModel):
    ids: list[str] = Field(..., min_length=1, description="arXiv 论文 ID 列表")


_ARXIV_SORT_BY = {
    "relevance": arxiv.SortCriterion.Relevance,
    "submitted_date": arxiv.SortCriterion.SubmittedDate,
    "last_updated_date": arxiv.SortCriterion.LastUpdatedDate,
}
_ARXIV_SORT_ORDER = {
    "descending": arxiv.SortOrder.Descending,
    "ascending": arxiv.SortOrder.Ascending,
}


def _serialize_arxiv_result(result: Any) -> dict[str, Any]:
    authors = [str(getattr(author, "name", "")).strip() for author in result.authors]
    short_id = str(result.get_short_id())
    entry_id = str(result.entry_id)
    return {
        "source_type": "paper",
        "source_provider": "arxiv",
        "retrieval_method": "fetch",
        "source_id": f"arxiv:{short_id}",
        "title": str(result.title),
        "summary": str(result.summary),
        "url": entry_id,
        "origin_url": entry_id,
        "arxiv_id": short_id,
        "authors": [name for name in authors if name],
        "published_at": result.published.isoformat() if result.published else None,
        "pdf_url": str(result.pdf_url or ""),
        "primary_category": str(result.primary_category or ""),
        "categories": list(result.categories or []),
    }


def build_arxiv_search_tool() -> BaseTool:
    async def _search(**kwargs: object) -> str:
        try:
            args = ArxivSearchArgs.model_validate(kwargs)
        except Exception:
            return _validation_error_output(
                code="ARXIV_SEARCH_BAD_REQUEST",
                message="arXiv 搜索参数错误",
                query=None,
                results=[],
            )
        try:
            client = arxiv.Client(page_size=args.max_results)
            search = arxiv.Search(
                query=args.query,
                max_results=args.max_results,
                sort_by=_ARXIV_SORT_BY[args.sort_by],
                sort_order=_ARXIV_SORT_ORDER[args.sort_order],
            )
            results = [
                _serialize_arxiv_result(result)
                for result in itertools.islice(client.results(search), args.max_results)
            ]
            payload = {
                "query": args.query,
                "parameters": args.model_dump(mode="json"),
                "total_found": len(results),
                "results": results,
                "error": None,
            }
        except Exception as exc:
            payload = {
                "query": args.query,
                "parameters": args.model_dump(mode="json"),
                "total_found": 0,
                "results": [],
                "error": {
                    "code": "ARXIV_SEARCH_UPSTREAM_ERROR",
                    "message": "arXiv 搜索暂时不可用，请稍后重试",
                    "retryable": False,
                    "detail": str(exc)[:300],
                },
            }
        return json.dumps(payload, ensure_ascii=False)

    return lc_tool(
        "arxiv_search",
        description="基于 arxiv.py 搜索论文。",
        args_schema=ArxivSearchArgs,
    )(_search)


def build_arxiv_fetch_tool() -> BaseTool:
    async def _fetch(**kwargs: object) -> str:
        try:
            args = ArxivFetchArgs.model_validate(kwargs)
        except Exception:
            return _validation_error_output(
                code="ARXIV_FETCH_BAD_REQUEST",
                message="arXiv 拉取参数错误",
                ids=[],
                results=[],
            )
        try:
            client = arxiv.Client(page_size=len(args.ids))
            search = arxiv.Search(id_list=list(args.ids))
            results = [
                _serialize_arxiv_result(result)
                for result in itertools.islice(client.results(search), len(args.ids))
            ]
            payload = {
                "ids": list(args.ids),
                "total_found": len(results),
                "results": results,
                "error": None,
            }
        except Exception as exc:
            payload = {
                "ids": list(args.ids),
                "total_found": 0,
                "results": [],
                "error": {
                    "code": "ARXIV_FETCH_UPSTREAM_ERROR",
                    "message": "arXiv 拉取暂时不可用，请稍后重试",
                    "retryable": False,
                    "detail": str(exc)[:300],
                },
            }
        return json.dumps(payload, ensure_ascii=False)

    return lc_tool(
        "arxiv_fetch",
        description="按 arXiv 论文 ID 拉取结构化论文元数据。",
        args_schema=ArxivFetchArgs,
    )(_fetch)
