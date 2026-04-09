"""Deep Research runtime 单入口。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from time import perf_counter
from types import SimpleNamespace
from typing import Any, cast

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.protocol import FileData
from deepagents.backends.utils import create_file_data
from langchain_core.messages import HumanMessage, ToolMessage
from langchain.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field, ValidationError

from app.agents.tool_calling.registry import (
    ToolMeta,
    build_research_tool_registry,
)
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.mcp_adapters import McpToolEntry
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.integrations.redis_client import RedisClient
from app.models.model_config import ModelProvider
from app.models.research_session import ResearchSession
from app.models.tool_extension import ToolExtension
from app.prompts import get_prompt_loader
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_query_mesh import (
    build_research_query_mesh,
    select_required_web_providers,
)
from app.services.research_runtime_context import (
    build_runtime_context_guide,
    build_runtime_context_snapshot,
)
from app.services.research_runtime_spill import spill_json_payload
from app.services.research_runtime_skills import build_research_runtime_skill_files
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
    ResearchRuntimeContext,
    ResearchToolRegistryBundle,
)
from app.services.research_source_bundle import ResearchSourceBundleBuilder
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_workspace_bootstrap_artifact_path_map,
)
from app.services.query_rewrite_service import coerce_structured_result_payload

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_WORKSPACE_CONTEXT_DOCS: tuple[tuple[str, Path], ...] = (
    (
        "/workspace/context/api_contract_research.md",
        _REPO_ROOT / "docs" / "api_contract_research.md",
    ),
    (
        "/workspace/context/research_design.md",
        _REPO_ROOT / "full-refactor-deep-research" / "design.md",
    ),
    (
        "/workspace/context/research_readme.md",
        _REPO_ROOT / "README.md",
    ),
)
_DEFAULT_RECOVERY_STRUCTURED_METHOD = "function_calling"
_OLLAMA_RECOVERY_STRUCTURED_METHOD = "json_mode"

AsyncInvoker = Callable[..., Awaitable[object]]
SyncInvoker = Callable[..., object]


class DeepResearchStructuredResponse(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[ResearchCanonicalCitation] = Field(min_length=2)


class DeepResearchCitationDraft(BaseModel):
    source_type: ResearchSourceType
    source_provider: str
    retrieval_method: str
    source_id: str
    title: str | None = None
    url: str | None = None
    origin_url: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: str | None = None
    pdf_url: str | None = None
    accessed_at: str | None = None


class DeepResearchStructuredResponseDraft(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[DeepResearchCitationDraft] = Field(min_length=2)


def _coerce_async_invoker(candidate: object) -> AsyncInvoker | None:
    if not callable(candidate):
        return None
    return cast(AsyncInvoker, candidate)


def _coerce_sync_invoker(candidate: object) -> SyncInvoker | None:
    if not callable(candidate):
        return None
    return cast(SyncInvoker, candidate)


async def _invoke_with_async_fallback(
    target: object,
    *args: Any,
    **kwargs: Any,
) -> object:
    ainvoke = _coerce_async_invoker(getattr(target, "ainvoke", None))
    if ainvoke is not None:
        return await ainvoke(*args, **kwargs)

    invoke = _coerce_sync_invoker(getattr(target, "invoke", None))
    if invoke is None:
        raise RuntimeError(
            "Deep Research runtime target does not support invoke/ainvoke"
        )
    return await asyncio.to_thread(invoke, *args, **kwargs)


def _normalize_structured_response_payload(payload: Any) -> Any:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)
    raw_citations = normalized.get("citations")
    if not isinstance(raw_citations, list):
        return normalized

    normalized_citations: list[Any] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            normalized_citations.append(item)
            continue

        citation = dict(item)
        if citation.get("source_type") == ResearchSourceType.WEB.value:
            origin_url = citation.get("origin_url")
            if not (isinstance(origin_url, str) and origin_url.strip()):
                fallback_origin_url = citation.get("url")
                if not (
                    isinstance(fallback_origin_url, str) and fallback_origin_url.strip()
                ):
                    fallback_origin_url = citation.get("source_id")
                if isinstance(fallback_origin_url, str) and fallback_origin_url.strip():
                    citation["origin_url"] = fallback_origin_url.strip()
        if citation.get("source_type") == ResearchSourceType.PAPER.value:
            raw_pdf_url = citation.get("pdf_url")
            if isinstance(raw_pdf_url, str):
                stripped_pdf_url = raw_pdf_url.strip()
                citation["pdf_url"] = stripped_pdf_url or None
            arxiv_id = citation.get("arxiv_id")
            if (
                not citation.get("pdf_url")
                and isinstance(arxiv_id, str)
                and arxiv_id.strip()
            ):
                citation["pdf_url"] = f"https://arxiv.org/pdf/{arxiv_id.strip()}.pdf"
        normalized_citations.append(citation)

    normalized["citations"] = normalized_citations
    return normalized


def _recover_structured_response_payload(result: dict[str, Any]) -> Any | None:
    structured_payload = result.get("structured_response")
    if structured_payload is not None:
        return structured_payload

    messages = result.get("messages")
    if not isinstance(messages, list):
        return None

    for message in reversed(messages):
        payload, _ = coerce_structured_result_payload(
            result={"raw": _structured_transport_message(message)},
            schema=DeepResearchStructuredResponseDraft,
        )
        if payload is not None:
            return payload
    return None


def _resolve_recovery_structured_output_method(
    *, settings: Settings | None = None
) -> str:
    try:
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=settings)
        provider = snapshot.active_provider_config().provider
    except RuntimeError:
        return _DEFAULT_RECOVERY_STRUCTURED_METHOD
    if provider == ModelProvider.OLLAMA:
        return _OLLAMA_RECOVERY_STRUCTURED_METHOD
    return _DEFAULT_RECOVERY_STRUCTURED_METHOD


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part.strip())
    return ""


def _message_field(message: Any, field_name: str) -> Any:
    if isinstance(message, dict):
        return message.get(field_name)
    return getattr(message, field_name, None)


def _message_type_name(message: Any) -> str:
    if isinstance(message, dict):
        raw_type = str(message.get("type") or "").strip().lower()
        return {
            "ai": "AIMessage",
            "tool": "ToolMessage",
            "human": "HumanMessage",
            "system": "SystemMessage",
        }.get(raw_type, "dict")
    return type(message).__name__


def _structured_transport_message(message: Any) -> Any:
    if not isinstance(message, dict):
        return message
    return SimpleNamespace(
        content=message.get("content"),
        tool_calls=message.get("tool_calls"),
        invalid_tool_calls=message.get("invalid_tool_calls"),
        additional_kwargs=message.get("additional_kwargs"),
    )


def _is_tool_message_like(message: Any) -> bool:
    return isinstance(message, ToolMessage) or (
        isinstance(message, dict)
        and str(message.get("type") or "").strip().lower() == "tool"
    )


def _load_tool_payload(message: Any) -> dict[str, Any] | None:
    text = _message_content_to_text(_message_field(message, "content"))
    if not text.strip():
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _recovery_tool_provider(tool_name: str) -> str | None:
    providers = {
        "jina_read": "jina_reader",
        "tavily_extract": "tavily",
        "tavily_crawl": "tavily",
        "web_extract": "tavily",
    }
    return providers.get(tool_name)


def _recovery_tool_method(tool_name: str) -> str:
    methods = {
        "web_search": "web_search",
        "jina_read": "read",
        "tavily_extract": "extract",
        "web_extract": "extract",
        "tavily_crawl": "crawl",
        "arxiv_search": "search",
        "arxiv_fetch": "fetch",
    }
    return methods.get(tool_name, tool_name or "tool")


def _coerce_recovered_citation_payload(item: Any) -> dict[str, Any] | None:
    candidate = item.model_dump(mode="json") if isinstance(item, BaseModel) else item
    if not isinstance(candidate, dict):
        return None
    try:
        return DeepResearchCitationDraft.model_validate(candidate).model_dump(
            mode="json"
        )
    except ValidationError:
        return None


def _recover_citation_payload_from_tool_result(
    *,
    tool_name: str,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name in {"arxiv_search", "arxiv_fetch"}:
        return _coerce_recovered_citation_payload(item)

    if tool_name == "jina_read":
        url = str(item.get("url") or "").strip()
        if not url:
            return None
        return _coerce_recovered_citation_payload(
            {
                "source_type": ResearchSourceType.WEB.value,
                "source_provider": "jina_reader",
                "retrieval_method": "read",
                "source_id": url,
                "title": str(item.get("title") or "").strip() or None,
                "url": url,
                "origin_url": url,
            }
        )

    url = str(item.get("origin_url") or item.get("url") or "").strip()
    source_provider = str(
        item.get("source_provider")
        or item.get("source")
        or _recovery_tool_provider(tool_name)
        or ""
    ).strip()
    if not (url and source_provider):
        return None
    return _coerce_recovered_citation_payload(
        {
            "source_type": ResearchSourceType.WEB.value,
            "source_provider": source_provider,
            "retrieval_method": _recovery_tool_method(tool_name),
            "source_id": str(item.get("source_id") or url).strip(),
            "title": str(item.get("title") or "").strip() or None,
            "url": str(item.get("url") or url).strip() or None,
            "origin_url": url,
            "published_at": str(item.get("published_at") or "").strip() or None,
        }
    )


def _dedupe_recovered_citation_payloads(
    citations: Sequence[Any],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in citations:
        payload = _coerce_recovered_citation_payload(item)
        if payload is None:
            continue
        locator = str(
            payload.get("source_id")
            or payload.get("origin_url")
            or payload.get("url")
            or ""
        ).strip()
        provider = str(payload.get("source_provider") or "").strip()
        if not (provider and locator):
            continue
        key = (provider, locator)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(payload)
    return deduped


def _recover_tool_evidence_citation_payloads(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    messages = result.get("messages")
    if not isinstance(messages, list):
        return []

    citations: list[dict[str, Any]] = []
    for message in messages:
        if not _is_tool_message_like(message):
            continue
        tool_name = str(_message_field(message, "name") or "").strip()
        if not tool_name:
            continue
        payload = _load_tool_payload(message)
        if payload is None or payload.get("error"):
            continue
        if tool_name == "jina_read":
            citation = _recover_citation_payload_from_tool_result(
                tool_name=tool_name, item=payload
            )
            if citation is not None:
                citations.append(citation)
            continue
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            continue
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            citation = _recover_citation_payload_from_tool_result(
                tool_name=tool_name, item=item
            )
            if citation is not None:
                citations.append(citation)
    return _dedupe_recovered_citation_payloads(citations)


def _select_runtime_tool(tools: Sequence[object], *, tool_name: str) -> object | None:
    for tool in tools:
        if str(getattr(tool, "name", "")).strip() == tool_name:
            return tool
    return None


async def _invoke_runtime_tool(
    tool: object, *, args: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        raw_output = await _invoke_with_async_fallback(tool, args)
    except RuntimeError:
        return None
    if not isinstance(raw_output, str):
        return None
    try:
        payload = json.loads(raw_output)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _build_prefetched_tool_message(
    *, tool_name: str, payload: dict[str, Any]
) -> ToolMessage:
    return ToolMessage(
        name=tool_name,
        tool_call_id=f"prefetch.{tool_name}:0",
        content=json.dumps(payload, ensure_ascii=False),
    )


async def _prefetch_required_external_tool_messages(
    *,
    question: str,
    plan_snapshot: ResearchPlanSnapshot,
    tools: Sequence[Any],
) -> list[ToolMessage]:
    query_mesh = build_research_query_mesh(
        question=question, plan_snapshot=plan_snapshot
    )
    prefetched_messages: list[ToolMessage] = []
    target_sources = set(plan_snapshot.target_sources)

    if ResearchSourceTarget.WEB in target_sources:
        web_search_tool = _select_runtime_tool(tools, tool_name="web_search")
        if web_search_tool is not None:
            web_payload = await _invoke_runtime_tool(
                web_search_tool,
                args={
                    "query": query_mesh.canonical_query,
                    "max_results": 6,
                },
            )
            if web_payload is not None:
                prefetched_messages.append(
                    _build_prefetched_tool_message(
                        tool_name="web_search", payload=web_payload
                    )
                )
                first_url = ""
                for item in web_payload.get("results") or []:
                    if not isinstance(item, dict):
                        continue
                    first_url = str(
                        item.get("origin_url") or item.get("url") or ""
                    ).strip()
                    if first_url:
                        break
                jina_read_tool = _select_runtime_tool(tools, tool_name="jina_read")
                if first_url and jina_read_tool is not None:
                    jina_payload = await _invoke_runtime_tool(
                        jina_read_tool,
                        args={"url": first_url},
                    )
                    if jina_payload is not None:
                        prefetched_messages.append(
                            _build_prefetched_tool_message(
                                tool_name="jina_read", payload=jina_payload
                            )
                        )

    if ResearchSourceTarget.PAPER in target_sources:
        arxiv_search_tool = _select_runtime_tool(tools, tool_name="arxiv_search")
        if arxiv_search_tool is not None:
            paper_query = (
                query_mesh.depth_queries[0]
                if query_mesh.depth_queries
                else query_mesh.canonical_query
            )
            arxiv_payload = await _invoke_runtime_tool(
                arxiv_search_tool,
                args={
                    "query": paper_query,
                    "max_results": 4,
                },
            )
            if arxiv_payload is not None:
                prefetched_messages.append(
                    _build_prefetched_tool_message(
                        tool_name="arxiv_search", payload=arxiv_payload
                    )
                )

    return prefetched_messages


def _needs_external_evidence_prefetch(
    *,
    citations: Sequence[ResearchCanonicalCitation],
    plan_snapshot: ResearchPlanSnapshot,
    required_web_providers: Sequence[str],
) -> bool:
    target_sources = set(plan_snapshot.target_sources)
    citation_providers = {citation.source_provider for citation in citations}
    has_paper_citation = any(
        citation.source_type == ResearchSourceType.PAPER for citation in citations
    )
    workspace_only = citation_providers <= {"workspace"}
    if ResearchSourceTarget.WEB in target_sources:
        if workspace_only:
            return True
        if any(
            provider not in citation_providers for provider in required_web_providers
        ):
            return True
    if ResearchSourceTarget.PAPER in target_sources and not has_paper_citation:
        return True
    return False


def _json_mode_schema_prompt(
    *,
    schema: type[BaseModel],
    instructions: Sequence[str],
    example_json: str | None = None,
) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    instruction_block = "\n".join(instructions)
    example_block = f"\n合法输出示例：\n{example_json}\n" if example_json else "\n"
    return (
        "你必须只返回一个 JSON 对象，不要输出 Markdown 代码块、解释、前后缀文本或额外字段。\n"
        "输出必须满足下面的 JSON Schema；即使某些字段为空，也必须按 schema 提供对应字段。\n"
        f"{instruction_block}"
        f"{example_block}"
        f"JSON Schema:\n{schema_json}"
    )


def _build_structured_recovery_prompt(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    transcript: str,
    method: str,
) -> str:
    instructions = [
        "- findings 至少 2 条，必须是可验证的具体结论。",
        "- citations 至少 2 条，必须对应 transcript 中真实出现的 title/url/source/provider 信息。",
        "- transcript 中已经出现的有效 citations 能保留多少就保留多少，不要为了压缩结果丢弃 provider 覆盖。",
        "- 若证据不足，请在 finding 文案中保留 limitation / uncertainty 语义，不要编造。",
    ]
    if method == _OLLAMA_RECOVERY_STRUCTURED_METHOD:
        example_json = json.dumps(
            {
                "findings": [
                    "过去一年 Agentic RAG 从概念探索转向多步编排实践。",
                    "GraphRAG 与评测体系更新正在同步推进，但仍有覆盖限制。",
                ],
                "citations": [
                    {
                        "source_type": "web",
                        "source_provider": "tavily",
                        "retrieval_method": "web_search",
                        "source_id": "https://example.com/rag-agentic",
                        "title": "Agentic RAG survey",
                        "url": "https://example.com/rag-agentic",
                        "origin_url": "https://example.com/rag-agentic",
                    },
                    {
                        "source_type": "paper",
                        "source_provider": "arxiv",
                        "retrieval_method": "search",
                        "source_id": "arxiv:2501.09136v4",
                        "title": "Agentic Retrieval-Augmented Generation",
                        "url": "https://arxiv.org/html/2501.09136v4",
                        "origin_url": "https://arxiv.org/html/2501.09136v4",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        schema_prompt = _json_mode_schema_prompt(
            schema=DeepResearchStructuredResponseDraft,
            instructions=instructions,
            example_json=example_json,
        )
        return (
            "请只根据下面的 deep research transcript 提炼结构化结果，然后按要求返回 JSON。\n"
            f"问题：{session.question}\n"
            f"research_brief：{plan_snapshot.research_brief}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"{schema_prompt}"
        )

    return "\n".join(
        [
            "请基于以下 deep research transcript 提炼结构化结果。",
            f"问题：{session.question}",
            f"research_brief：{plan_snapshot.research_brief}",
            "输出要求：",
            *instructions,
            "",
            "Transcript:",
            transcript,
        ]
    )


def _merge_recovered_citations_into_payload(
    *,
    payload: Any,
    recovered_citations: Sequence[dict[str, Any]],
) -> Any:
    if not recovered_citations:
        return payload
    normalized_payload = (
        payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    )
    if not isinstance(normalized_payload, dict):
        return payload
    existing_citations = normalized_payload.get("citations")
    merged_citations = _dedupe_recovered_citation_payloads(
        [
            *(existing_citations if isinstance(existing_citations, list) else []),
            *recovered_citations,
        ]
    )
    normalized = dict(normalized_payload)
    normalized["citations"] = merged_citations
    return normalized


def _truncate_preview(value: Any, *, limit: int) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        rendered = repr(value)
    rendered = rendered.strip()
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[:limit]}..."


def _build_runtime_result_snapshot(
    result: dict[str, Any],
    *,
    tail_messages: int = 3,
) -> dict[str, Any]:
    messages = result.get("messages")
    files = result.get("files")
    structured_response = result.get("structured_response")
    transcript = _build_structured_recovery_transcript(
        result,
        max_messages=tail_messages,
        content_limit=600,
        tool_limit=240,
    )

    tail_message_summaries: list[dict[str, Any]] = []
    if isinstance(messages, list):
        start_index = max(0, len(messages) - tail_messages)
        for index, message in enumerate(messages[start_index:], start=start_index):
            tail_message_summaries.append(
                {
                    "index": index,
                    "type": _message_type_name(message),
                    "has_tool_calls": bool(_message_field(message, "tool_calls")),
                    "content_preview": _truncate_preview(
                        _message_field(message, "content"),
                        limit=240,
                    ),
                }
            )

    return {
        "result_keys": sorted(str(key) for key in result.keys()),
        "structured_response_present": "structured_response" in result,
        "structured_response_type": (
            type(structured_response).__name__
            if structured_response is not None
            else None
        ),
        "messages_type": type(messages).__name__ if messages is not None else None,
        "messages_count": len(messages) if isinstance(messages, list) else None,
        "message_types_tail": (
            [_message_type_name(message) for message in messages[-tail_messages:]]
            if isinstance(messages, list)
            else []
        ),
        "tail_message_summaries": tail_message_summaries,
        "files_type": type(files).__name__ if files is not None else None,
        "file_count": len(files) if isinstance(files, dict) else None,
        "file_paths_preview": (
            sorted(str(path) for path in files.keys())[:6]
            if isinstance(files, dict)
            else []
        ),
        "recovery_transcript_present": bool(transcript),
        "recovery_transcript_preview": (
            _truncate_preview(transcript, limit=800) if transcript else ""
        ),
        "tool_evidence_citation_count": len(
            _recover_tool_evidence_citation_payloads(result)
        ),
    }


def _build_structured_recovery_transcript(
    result: dict[str, Any],
    *,
    max_messages: int = 18,
    content_limit: int = 4_000,
    tool_limit: int = 1_200,
) -> str:
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        return ""

    lines: list[str] = []
    start_index = max(0, len(messages) - max_messages)
    for index, message in enumerate(messages[start_index:], start=start_index):
        content_preview = _truncate_preview(
            _message_field(message, "content"), limit=content_limit
        )
        tool_calls = _message_field(message, "tool_calls")
        lines.extend(
            [
                f"## message[{index}] {_message_type_name(message)}",
                f"content: {content_preview}",
            ]
        )
        if tool_calls:
            lines.append(
                f"tool_calls: {_truncate_preview(tool_calls, limit=tool_limit)}"
            )
        lines.append("")

    files = result.get("files")
    if isinstance(files, dict) and files:
        lines.append(
            "available_files: " + ", ".join(sorted(str(path) for path in files.keys()))
        )

    return "\n".join(lines).strip()


async def _synthesize_structured_response_from_result(
    *,
    result: dict[str, Any],
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    model: Any,
    structured_method: str,
) -> Any | None:
    transcript = _build_structured_recovery_transcript(result)
    if not transcript:
        return None

    recovery_prompt = _build_structured_recovery_prompt(
        session=session,
        plan_snapshot=plan_snapshot,
        transcript=transcript,
        method=structured_method,
    )
    structured_model = model.with_structured_output(
        DeepResearchStructuredResponseDraft,
        method=structured_method,
        include_raw=True,
    )
    recovery_result = await structured_model.ainvoke(
        [HumanMessage(content=recovery_prompt)]
    )
    payload, _ = coerce_structured_result_payload(
        result=recovery_result,
        schema=DeepResearchStructuredResponseDraft,
    )
    if payload is None:
        return None
    return _merge_recovered_citations_into_payload(
        payload=payload,
        recovered_citations=_recover_tool_evidence_citation_payloads(result),
    )


@dataclass(slots=True)
class DeepResearchRuntime:
    """研究运行时句柄。"""

    agent: Any
    config: ResearchRuntimeConfig
    tools: list[BaseTool]
    tool_meta_by_name: dict[str, ToolMeta]
    tool_groups: dict[str, tuple[str, ...]]

    def make_run_config(self, *, thread_id: str) -> dict[str, Any]:
        return build_research_run_config(thread_id=thread_id)

    def stream_kwargs(self) -> dict[str, Any]:
        return self.config.stream_policy.as_kwargs()


def build_research_run_config(*, thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _build_runtime_context(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    layout: Any,
) -> ResearchRuntimeContext:
    return ResearchRuntimeContext(
        session_id=str(session.id),
        thread_id=str(session.thread_id),
        trace_id=str(getattr(session, "trace_id", "") or "") or None,
        target_sources=tuple(item.value for item in plan_snapshot.target_sources),
        subagent_route=resolve_source_subagent_route(plan_snapshot.target_sources),
        workspace_root=str(layout.workspace_root),
        scratch_root=str(layout.scratch_root),
    )


def build_research_backend(
    policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY,
) -> CompositeBackend:
    """构建 CompositeBackend，明确分离临时上下文与持久记忆/技能。"""

    state_backend = StateBackend()
    store_backend = StoreBackend()
    return CompositeBackend(
        default=state_backend,
        routes={
            policy.memories_root: store_backend,
            policy.skills_root: store_backend,
        },
    )


def _select_tools_by_name(
    tools: Sequence[BaseTool],
    *,
    tool_names: Sequence[str],
) -> list[BaseTool]:
    wanted = {name for name in tool_names}
    return [tool for tool in tools if tool.name in wanted]


def _build_source_specialized_subagents(
    *,
    config: ResearchRuntimeConfig,
    tools: Sequence[BaseTool],
    tool_groups: dict[str, tuple[str, ...]],
    resolved_skill_paths: Sequence[str],
) -> list[dict[str, Any]]:
    general_purpose_subagent: dict[str, Any] = {
        "name": config.subagent_name,
        "description": config.subagent_description,
        "system_prompt": config.system_prompt,
        "tools": list(tools),
        "model": config.subagent_model,
    }
    if resolved_skill_paths:
        general_purpose_subagent["skills"] = list(resolved_skill_paths)
    if config.interrupt_on:
        general_purpose_subagent["interrupt_on"] = dict(config.interrupt_on)

    subagents: list[dict[str, Any]] = [general_purpose_subagent]
    for name, description in (
        ("web", "网页来源子代理：负责 Tavily、Jina Reader、SearXNG 路线。"),
        ("paper", "论文来源子代理：负责 arXiv 搜索与论文基线构建。"),
    ):
        group_tools = _select_tools_by_name(tools, tool_names=tool_groups.get(name, ()))
        if not group_tools:
            continue
        subagent: dict[str, Any] = {
            "name": name,
            "description": description,
            "system_prompt": config.system_prompt,
            "tools": group_tools,
            "model": config.subagent_model,
        }
        if resolved_skill_paths:
            subagent["skills"] = list(resolved_skill_paths)
        if config.interrupt_on:
            subagent["interrupt_on"] = dict(config.interrupt_on)
        subagents.append(subagent)

    citation_subagent: dict[str, Any] = {
        "name": "citation",
        "description": "引用与报告子代理：负责 finalizer 前的 citation/report 收口。",
        "system_prompt": config.system_prompt,
        "model": config.finalizer_model,
    }
    if resolved_skill_paths:
        citation_subagent["skills"] = list(resolved_skill_paths)
    subagents.append(citation_subagent)
    return subagents


def resolve_source_subagent_route(
    target_sources: Sequence[ResearchSourceTarget],
) -> tuple[str, ...]:
    normalized = {item for item in target_sources}
    if (
        ResearchSourceTarget.WEB in normalized
        and ResearchSourceTarget.PAPER in normalized
    ):
        return ("paper", "web", "citation")
    if ResearchSourceTarget.PAPER in normalized:
        return ("paper", "citation")
    if ResearchSourceTarget.WEB in normalized:
        return ("web", "citation")
    return ("citation",)


async def create_deep_research_runtime(
    *,
    settings: Settings,
    config: ResearchRuntimeConfig,
    response_format: Any | None = None,
    extensions: Sequence[ToolExtension] | None = None,
    mcp_entries: Sequence[McpToolEntry] | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
    redis: RedisClient | None = None,
    http_client: Any | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> DeepResearchRuntime:
    """构建 Deep Agents research runtime。

    当前仅落地单入口 harness 与固定运行策略；
    source-aware provider 细化与 finalizer 留待后续任务继续扩展。
    """

    registry_bundle: ResearchToolRegistryBundle = await build_research_tool_registry(
        settings=settings,
        extra_tools=extra_tools,
        redis=redis,
        http_client=http_client,
    )
    del extensions, mcp_entries

    tools = registry_bundle.tools
    tool_meta_by_name = registry_bundle.tool_meta_by_name

    resolved_checkpointer = checkpointer
    resolved_store = store
    resolved_skill_paths = list(config.skill_paths)

    agent_kwargs: dict[str, Any] = {
        "name": config.name,
        "model": config.primary_model,
        "tools": tools,
        "system_prompt": config.system_prompt,
        "subagents": _build_source_specialized_subagents(
            config=config,
            tools=tools,
            tool_groups=registry_bundle.tool_groups,
            resolved_skill_paths=resolved_skill_paths,
        ),
        "skills": resolved_skill_paths,
        "memory": list(config.memory_paths),
        "checkpointer": resolved_checkpointer,
        "store": resolved_store,
        "backend": build_research_backend(config.backend_policy),
        "context_schema": ResearchRuntimeContext,
        "interrupt_on": dict(config.interrupt_on) if config.interrupt_on else None,
    }
    if response_format is not None:
        agent_kwargs["response_format"] = response_format

    agent = create_deep_agent(**agent_kwargs)
    return DeepResearchRuntime(
        agent=agent,
        config=config,
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        tool_groups=registry_bundle.tool_groups,
    )


def _build_workspace_context_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for virtual_path, disk_path in _DEFAULT_WORKSPACE_CONTEXT_DOCS:
        if not disk_path.exists():
            continue
        files[virtual_path] = disk_path.read_text(encoding="utf-8")
    return files


def _to_file_uri(path: str) -> str:
    normalized = "/" + path.lstrip("/")
    return f"file://{normalized}"


def _format_workspace_paths_block(workspace_paths: Sequence[str]) -> str:
    return "\n".join(f"- {path}" for path in workspace_paths)


def _build_runtime_prompt(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    workspace_paths: Sequence[str],
) -> str:
    prompt_loader = get_prompt_loader()
    route_hint = ", ".join(resolve_source_subagent_route(plan_snapshot.target_sources))
    return prompt_loader.render_with_few_shot(
        "research/runtime_user",
        question=session.question,
        research_brief=plan_snapshot.research_brief,
        target_sources=", ".join(item.value for item in plan_snapshot.target_sources),
        route_hint=route_hint,
        workspace_paths_block=_format_workspace_paths_block(workspace_paths),
    )


def _build_runtime_request_files(
    *,
    workspace_files: dict[str, str],
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, FileData]:
    query_mesh = build_research_query_mesh(
        question=session.question,
        plan_snapshot=plan_snapshot,
    )
    request_files: dict[str, FileData] = {
        path: create_file_data(content) for path, content in workspace_files.items()
    }
    request_files["/workspace/context/session_question.txt"] = create_file_data(
        session.question
    )
    request_files["/workspace/context/plan_snapshot.json"] = create_file_data(
        json.dumps(plan_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    request_files["/workspace/context/query_mesh.json"] = create_file_data(
        json.dumps(asdict(query_mesh), ensure_ascii=False, indent=2)
    )
    return request_files


def _artifact_spill_slug_for_workspace_path(workspace_path: str) -> str:
    filename = PurePosixPath(workspace_path).name
    if filename.endswith(".md"):
        return filename[:-3]
    return filename


def _require_preloaded_session_artifacts(session: ResearchSession) -> Sequence[Any]:
    if "artifacts" not in session.__dict__:
        raise RuntimeError(
            "Deep Research runtime requires session.artifacts to be preloaded."
        )
    return session.artifacts or ()


def _build_bootstrap_workspace_file_entries(
    *,
    artifacts: Sequence[Any],
    layout: Any,
    path_by_artifact_key: dict[str, str],
    large_result_policy: Any,
) -> list[tuple[str, str]]:
    workspace_entries: list[tuple[str, str]] = []
    for artifact in artifacts:
        artifact_key = getattr(artifact, "artifact_key", None)
        if not isinstance(artifact_key, str):
            continue
        workspace_path = path_by_artifact_key.get(artifact_key)
        if workspace_path is None:
            continue
        content_text = getattr(artifact, "content_text", None)
        if not isinstance(content_text, str):
            continue
        if len(content_text) <= large_result_policy.max_inline_chars:
            workspace_entries.append((workspace_path, content_text))
            continue

        spill_prefix = (
            f"{large_result_policy.spill_path_prefix.rstrip('/')}/{layout.session_slug}"
        )
        spill_result = spill_json_payload(
            layout=layout,
            provider="workspace-bootstrap",
            slug=_artifact_spill_slug_for_workspace_path(workspace_path),
            payload={
                "artifact_key": artifact_key,
                "workspace_path": workspace_path,
                "content_text": content_text,
            },
            summary_lines=[
                f"- spilled artifact: {artifact_key}",
                f"- workspace path: {workspace_path}",
                f"- original size chars: {len(content_text)}",
            ],
            path_prefix=spill_prefix,
        )
        workspace_entries.extend(
            [
                (
                    workspace_path,
                    "\n".join(
                        [
                            "# Bootstrap Artifact Spill",
                            "",
                            f"- artifact_key: `{artifact_key}`",
                            f"- original_workspace_path: `{workspace_path}`",
                            f"- spill_summary_path: `{spill_result.summary_path}`",
                            f"- spill_raw_path: `{spill_result.raw_path}`",
                            f"- original_size_chars: {len(content_text)}",
                            "",
                            "请优先继续读取上述 spill 文件。",
                        ]
                    )
                    + "\n",
                ),
                (spill_result.summary_path, spill_result.summary_content),
                (spill_result.raw_path, spill_result.raw_content),
            ]
        )
    return workspace_entries


def _build_session_bootstrap_workspace_files(
    *,
    session: ResearchSession,
    large_result_policy: Any,
) -> dict[str, str]:
    artifacts = _require_preloaded_session_artifacts(session)
    if not artifacts:
        return {}

    layout = build_research_workspace_layout(session.id)
    path_by_artifact_key = build_workspace_bootstrap_artifact_path_map(layout=layout)
    return dict(
        _build_bootstrap_workspace_file_entries(
            artifacts=artifacts,
            layout=layout,
            path_by_artifact_key=path_by_artifact_key,
            large_result_policy=large_result_policy,
        )
    )


@dataclass(slots=True)
class DeepResearchRuntimeRunner:
    runtime: DeepResearchRuntime
    workspace_files: dict[str, str]

    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        layout = build_research_workspace_layout(session.id)
        workspace_files = dict(self.workspace_files)
        workspace_files.update(build_research_runtime_skill_files())
        workspace_files.update(
            _build_session_bootstrap_workspace_files(
                session=session,
                large_result_policy=self.runtime.config.large_result_policy,
            )
        )
        context_guide = build_runtime_context_guide(
            workspace_files=workspace_files,
            layout=layout,
        )
        workspace_files[context_guide.path] = context_guide.content
        request_files = _build_runtime_request_files(
            workspace_files=workspace_files,
            session=session,
            plan_snapshot=plan_snapshot,
        )
        prompt = _build_runtime_prompt(
            session=session,
            plan_snapshot=plan_snapshot,
            workspace_paths=context_guide.priority_paths,
        )
        request: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "files": request_files,
        }
        config = self.runtime.make_run_config(thread_id=session.thread_id)
        runtime_context = _build_runtime_context(
            session=session,
            plan_snapshot=plan_snapshot,
            layout=layout,
        )
        started_at = perf_counter()
        result = await _invoke_with_async_fallback(
            self.runtime.agent,
            request,
            config,
            context=runtime_context,
        )
        latency_ms = int((perf_counter() - started_at) * 1000)
        if not isinstance(result, dict):
            raise RuntimeError("Deep Research runtime 返回类型不符合预期")

        structured_payload = _recover_structured_response_payload(result)
        if structured_payload is None:
            structured_payload = await _synthesize_structured_response_from_result(
                result=result,
                session=session,
                plan_snapshot=plan_snapshot,
                model=self.runtime.config.finalizer_model,
                structured_method=self.runtime.config.finalizer_structured_method,
            )
        if structured_payload is None:
            result_snapshot = _build_runtime_result_snapshot(result)
            raise RuntimeError(
                "Deep Research runtime 未返回 structured_response; result_snapshot="
                + json.dumps(result_snapshot, ensure_ascii=False, sort_keys=True)
            )
        recovered_citations = _recover_tool_evidence_citation_payloads(result)
        structured_payload = _merge_recovered_citations_into_payload(
            payload=structured_payload,
            recovered_citations=recovered_citations,
        )
        try:
            structured = DeepResearchStructuredResponse.model_validate(
                _normalize_structured_response_payload(structured_payload)
            )
        except ValidationError as exc:
            raise RuntimeError(
                "Deep Research runtime structured_response 不符合契约"
            ) from exc
        required_web_providers = (
            select_required_web_providers(
                complexity=plan_snapshot.complexity.value,
                available_providers=self.runtime.tool_groups["web_provider_ids"],
            )
            if ResearchSourceTarget.WEB in set(plan_snapshot.target_sources)
            else ()
        )
        if _needs_external_evidence_prefetch(
            citations=structured.citations,
            plan_snapshot=plan_snapshot,
            required_web_providers=required_web_providers,
        ):
            prefetched_messages = await _prefetch_required_external_tool_messages(
                question=session.question,
                plan_snapshot=plan_snapshot,
                tools=self.runtime.tools,
            )
            if prefetched_messages:
                existing_messages = result.get("messages")
                augmented_result = dict(result)
                augmented_result["messages"] = [
                    *(existing_messages if isinstance(existing_messages, list) else []),
                    *prefetched_messages,
                ]
                synthesized_payload = await _synthesize_structured_response_from_result(
                    result=augmented_result,
                    session=session,
                    plan_snapshot=plan_snapshot,
                    model=self.runtime.config.finalizer_model,
                    structured_method=self.runtime.config.finalizer_structured_method,
                )
                if synthesized_payload is not None:
                    recovered_citations = _recover_tool_evidence_citation_payloads(
                        augmented_result
                    )
                    structured_payload = _merge_recovered_citations_into_payload(
                        payload=synthesized_payload,
                        recovered_citations=recovered_citations,
                    )
                    try:
                        structured = DeepResearchStructuredResponse.model_validate(
                            _normalize_structured_response_payload(structured_payload)
                        )
                    except ValidationError as exc:
                        raise RuntimeError(
                            "Deep Research runtime structured_response 不符合契约"
                        ) from exc

        workspace_only_web_citations = bool(structured.citations) and all(
            citation.source_type == ResearchSourceType.WEB
            and citation.source_provider == "workspace"
            for citation in structured.citations
        )

        source_bundle = ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=structured.citations,
            findings=structured.findings,
            required_web_providers=(
                required_web_providers
                if ResearchSourceTarget.WEB in set(plan_snapshot.target_sources)
                and not workspace_only_web_citations
                else ()
            ),
        )
        runtime_context_snapshot = build_runtime_context_snapshot(
            result=result,
            layout=layout,
        )
        return ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            runtime_context_snapshot=runtime_context_snapshot,
            latency_ms=latency_ms,
        )


async def build_deep_research_runtime_runner(
    *,
    settings: Settings,
    http_client: Any | None = None,
    redis: RedisClient | None = None,
) -> DeepResearchRuntimeRunner:
    prompt_loader = get_prompt_loader()
    runtime_config = ResearchRuntimeConfig(
        primary_model=create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        ),
        subagent_model=create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        ),
        finalizer_model=create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        ),
        finalizer_structured_method=_resolve_recovery_structured_output_method(
            settings=settings
        ),
        system_prompt=prompt_loader.render_with_few_shot("research/runtime_system"),
    )
    runtime = await create_deep_research_runtime(
        settings=settings,
        config=runtime_config,
        # 运行时先接受缺少 origin_url 的 citation 草稿，随后在 runner 侧统一补齐并
        # 收敛到严格的 DeepResearchStructuredResponse 契约，避免模型输出因细小字段遗漏
        # 被 runtime 提前拒绝。
        response_format=DeepResearchStructuredResponseDraft,
        http_client=http_client,
        redis=redis,
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
    )
    return DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files=_build_workspace_context_files(),
    )
