from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Awaitable, cast

from deepagents.backends.protocol import FileData
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config.provider_registry import resolve_langchain_structured_output_method
from app.core.settings import Settings
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.research_session import ResearchSession
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchPlanSnapshot,
    ResearchSourceType,
)
from app.services.query_rewrite_service import coerce_structured_result_payload

_DEFAULT_RECOVERY_STRUCTURED_METHOD = "function_calling"
_MISSING_STRUCTURED_RESPONSE_CONTINUE_LIMIT = 1
_MISSING_STRUCTURED_RESPONSE_CONTINUE_PROMPT = (
    "继续当前 deep research。不要停留在“研究已启动”或阶段性说明。"
    "请完成仍处于进行中或待完成的 todos/subtasks，继续调用必要工具或子代理，"
    "并返回最终 structured_response，至少包含 2 条 findings 和 2 条 citations。"
)

class DeepResearchStructuredResponse(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[ResearchCanonicalCitation] = Field(min_length=2)


class DeepResearchCitationDraft(BaseModel):
    source_type: ResearchSourceType
    source_provider: str = Field(min_length=1)
    retrieval_method: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    title: str | None = None
    url: str | None = None
    origin_url: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: str | None = None
    pdf_url: str | None = None
    accessed_at: str | None = None
    retrieved_at: datetime
    excerpts: list[ResearchCitationExcerpt] = Field(min_length=1, max_length=5)


class DeepResearchStructuredResponseDraft(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[DeepResearchCitationDraft] = Field(min_length=2)


async def _invoke_with_async_fallback(target: object, args: dict[str, Any]) -> object:
    ainvoke = getattr(target, "ainvoke", None)
    if callable(ainvoke):
        return await cast(Awaitable[object], ainvoke(args))
    invoke = getattr(target, "invoke", None)
    if callable(invoke):
        return await asyncio.to_thread(invoke, args)
    raise RuntimeError("Deep Research runtime target does not support invoke/ainvoke")


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
        if not citation.get("retrieved_at"):
            citation["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        normalized_citations.append(citation)

    normalized["citations"] = normalized_citations
    return normalized

def _result_has_pending_todos(result: dict[str, Any]) -> bool:
    todos = result.get("todos")
    return isinstance(todos, list) and len(todos) > 0


def _build_missing_structured_response_continue_request(
    *,
    request_files: dict[str, FileData],
) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": _MISSING_STRUCTURED_RESPONSE_CONTINUE_PROMPT,
            }
        ],
        "files": request_files,
    }



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


def resolve_recovery_structured_output_method(
    *, settings: Settings | None = None
) -> str:
    try:
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=settings)
        provider = snapshot.active_provider_config().provider
    except RuntimeError:
        return _DEFAULT_RECOVERY_STRUCTURED_METHOD
    return resolve_langchain_structured_output_method(
        provider,
        default=_DEFAULT_RECOVERY_STRUCTURED_METHOD,
    )


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
    if method == "json_mode":
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
    return payload
