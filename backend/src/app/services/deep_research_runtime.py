"""Deep Research runtime 单入口。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, TypeGuard, cast

from langchain.tools import BaseTool, ToolRuntime, tool as lc_tool
from pydantic import BaseModel, Field, ValidationError

from app.config.runtime_contract import (
    RESEARCH_RUNTIME_REQUEST_CONTEXT,
    RESEARCH_RUNTIME_WORKSPACE_CONTEXT_DOCS,
)
from app.core.checkpoint import CheckpointManager
from app.core.memory_store import StoreManager
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.redis_client import RedisClient
from app.models.research_session import ResearchSession
from app.prompts import get_prompt_loader
from app.schemas.research import ResearchPlanSnapshot, ResearchSourceTarget, ResearchSourceType
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_query_mesh import select_required_web_providers
from app.services.research_runtime_context import (
    build_runtime_context_guide,
    build_runtime_context_snapshot,
)
from app.services.research_runtime_factory import (
    DeepResearchRuntime,
    _build_source_specialized_subagents,  # noqa: F401
    create_deep_research_runtime,
    resolve_source_subagent_route,
)
from app.services.research_runtime_recovery import (
    DeepResearchStructuredResponse,
    DeepResearchStructuredResponseDraft,
    _MISSING_STRUCTURED_RESPONSE_CONTINUE_LIMIT,
    _build_missing_structured_response_continue_request,
    _build_runtime_result_snapshot,
    _merge_recovered_citations_into_payload,
    _needs_external_evidence_prefetch,
    _normalize_structured_response_payload,
    _prefetch_required_external_tool_messages,
    _recover_structured_response_payload,
    _recover_tool_evidence_citation_payloads,
    _result_has_pending_todos,
    _synthesize_structured_response_from_result,
    resolve_recovery_structured_output_method as _resolve_recovery_structured_output_method,
)
from app.services.research_runtime_skills import build_research_runtime_skill_files
from app.services.research_runtime_types import (
    ResearchRuntimeActivityStatus,
    ResearchRuntimeActivityUpdate,
    ResearchRuntimeConfig,
    ResearchRuntimeContext,
)
from app.services.research_runtime_workspace import (
    DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH,
    build_runtime_memory_files as _build_runtime_memory_files,
    build_runtime_prompt as _build_runtime_prompt,
    build_runtime_request_files as _build_runtime_request_files,
    build_session_bootstrap_workspace_files as _build_session_bootstrap_workspace_files,
)
from app.services.research_source_bundle import ResearchSourceBundleBuilder
from app.services.research_workspace_files import (
    build_runtime_orchestration_scaffold_files,
    build_research_workspace_layout,
)

AsyncInvoker = Callable[..., Awaitable[object]]
SyncInvoker = Callable[..., object]

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

def _normalize_plan_progress_message(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None

def _is_runtime_result_mapping(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


class _RuntimeActivityCallbackRegistry:
    def __init__(self) -> None:
        self._callbacks: dict[
            str, Callable[[ResearchRuntimeActivityUpdate], Awaitable[None]]
        ] = {}

    def register(
        self,
        session_id: str,
        callback: Callable[[ResearchRuntimeActivityUpdate], Awaitable[None]],
    ) -> None:
        self._callbacks[session_id] = callback

    def unregister(self, session_id: str) -> None:
        self._callbacks.pop(session_id, None)

    def sole_session_id(self) -> str | None:
        if len(self._callbacks) != 1:
            return None
        return next(iter(self._callbacks))

    async def dispatch(
        self,
        *,
        session_id: str,
        update: ResearchRuntimeActivityUpdate,
    ) -> None:
        callback = self._callbacks.get(session_id)
        if callback is None:
            raise RuntimeError(
                f"Deep Research runtime 未找到 session={session_id} 的活动回调"
            )
        await callback(update)


class _RecordRuntimeActivityInput(BaseModel):
    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    task_kind: str = Field(min_length=1)
    status: ResearchRuntimeActivityStatus
    agent_name: str = Field(min_length=1)
    subagent_name: str | None = None
    parallel_group: str | None = None
    message: str | None = None


def _runtime_context_session_id(
    runtime: ToolRuntime | None,
    *,
    fallback_session_id: str | None = None,
) -> str:
    context = getattr(runtime, "context", None)
    if isinstance(context, ResearchRuntimeContext):
        return context.session_id
    if isinstance(context, dict):
        value = context.get("session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(fallback_session_id, str) and fallback_session_id.strip():
        return fallback_session_id.strip()
    raise RuntimeError("Deep Research runtime context 缺少 session_id")


def _build_record_runtime_activity_tool(
    registry: _RuntimeActivityCallbackRegistry,
) -> BaseTool:
    @lc_tool("record_runtime_activity", args_schema=_RecordRuntimeActivityInput)
    async def _record_runtime_activity(  # type: ignore[misc]
        task_id: str,
        title: str,
        task_kind: str,
        status: ResearchRuntimeActivityStatus,
        agent_name: str,
        subagent_name: str | None = None,
        parallel_group: str | None = None,
        message: str | None = None,
        runtime: ToolRuntime | None = None,
    ) -> str:
        """记录 runtime 当前 agent、任务与并行分组进展。"""

        session_id = _runtime_context_session_id(
            runtime,
            fallback_session_id=registry.sole_session_id(),
        )
        await registry.dispatch(
            session_id=session_id,
            update=ResearchRuntimeActivityUpdate(
                task_id=task_id.strip(),
                title=title.strip(),
                task_kind=task_kind.strip(),
                status=status,
                agent_name=agent_name.strip(),
                subagent_name=(
                    subagent_name.strip()
                    if isinstance(subagent_name, str) and subagent_name.strip()
                    else None
                ),
                parallel_group=(
                    parallel_group.strip()
                    if isinstance(parallel_group, str) and parallel_group.strip()
                    else None
                ),
                message=_normalize_plan_progress_message(message),
            ),
        )
        return f"任务活动已记录：{title}"

    return _record_runtime_activity

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

def _build_workspace_context_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for doc in RESEARCH_RUNTIME_WORKSPACE_CONTEXT_DOCS:
        if not doc.disk_path.exists():
            continue
        files[doc.virtual_path] = doc.disk_path.read_text(encoding="utf-8")
    return files

@dataclass(slots=True)
class DeepResearchRuntimeRunner:
    runtime: DeepResearchRuntime
    workspace_files: dict[str, str]
    runtime_activity_registry: _RuntimeActivityCallbackRegistry | None = None

    async def _recover_structured_payload(
        self,
        *,
        result: dict[str, Any],
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> Any | None:
        structured_payload = _recover_structured_response_payload(result)
        if structured_payload is not None:
            return structured_payload
        return await _synthesize_structured_response_from_result(
            result=result,
            session=session,
            plan_snapshot=plan_snapshot,
            model=self.runtime.config.finalizer_model,
            structured_method=self.runtime.config.finalizer_structured_method,
        )

    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        runtime_activity_callback: Callable[
            [ResearchRuntimeActivityUpdate], Awaitable[None]
        ]
        | None = None,
    ) -> ResearchRuntimeRunResult:
        layout = build_research_workspace_layout(session.id)
        workspace_files = dict(self.workspace_files)
        workspace_files.update(build_research_runtime_skill_files())
        workspace_files.update(
            build_runtime_orchestration_scaffold_files(
                question=session.question,
                plan_snapshot=plan_snapshot,
                layout=layout,
            )
        )
        workspace_files.update(
            _build_session_bootstrap_workspace_files(
                session=session,
                large_result_policy=self.runtime.config.large_result_policy,
            )
        )
        workspace_files.update(
            _build_runtime_memory_files(
                session=session,
                plan_snapshot=plan_snapshot,
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
        if runtime_activity_callback is not None:
            if self.runtime_activity_registry is None:
                raise RuntimeError("Deep Research runtime 未配置活动回调注册器")
            self.runtime_activity_registry.register(
                str(session.id),
                runtime_activity_callback,
            )
        try:
            result = await _invoke_with_async_fallback(
                self.runtime.agent,
                request,
                config,
                context=runtime_context,
            )
            if not _is_runtime_result_mapping(result):
                raise RuntimeError("Deep Research runtime 返回类型不符合预期")
            structured_payload = await self._recover_structured_payload(
                result=result,
                session=session,
                plan_snapshot=plan_snapshot,
            )
            continuation_count = 0
            while (
                structured_payload is None
                and continuation_count < _MISSING_STRUCTURED_RESPONSE_CONTINUE_LIMIT
                and _result_has_pending_todos(result)
            ):
                continuation_count += 1
                result = await _invoke_with_async_fallback(
                    self.runtime.agent,
                    _build_missing_structured_response_continue_request(
                        request_files=request_files,
                    ),
                    config,
                    context=runtime_context,
                )
                if not _is_runtime_result_mapping(result):
                    raise RuntimeError("Deep Research runtime 返回类型不符合预期")
                structured_payload = await self._recover_structured_payload(
                    result=result,
                    session=session,
                    plan_snapshot=plan_snapshot,
                )
        finally:
            if (
                runtime_activity_callback is not None
                and self.runtime_activity_registry is not None
            ):
                self.runtime_activity_registry.unregister(str(session.id))
        latency_ms = int((perf_counter() - started_at) * 1000)
        if not _is_runtime_result_mapping(result):
            raise RuntimeError("Deep Research runtime 返回类型不符合预期")

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
            baseline_files=workspace_files,
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
    await CheckpointManager.initialize()
    await StoreManager.initialize()
    prompt_loader = get_prompt_loader()
    runtime_activity_registry = _RuntimeActivityCallbackRegistry()
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
        system_prompt=prompt_loader.render_with_few_shot(
            "research/runtime_system",
            context_root=RESEARCH_RUNTIME_REQUEST_CONTEXT.context_root,
        ),
        memory_paths=(DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH,),
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
        checkpointer=CheckpointManager.get_checkpointer(),
        store=StoreManager.get_store(),
        extra_tools=[
            _build_record_runtime_activity_tool(runtime_activity_registry),
        ],
    )
    return DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files=_build_workspace_context_files(),
        runtime_activity_registry=runtime_activity_registry,
    )
