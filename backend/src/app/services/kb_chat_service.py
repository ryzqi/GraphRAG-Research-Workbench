"""知识库问答服务。

使用 LangGraph 图实现，支持检查点持久化。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_chat_agentic_state import build_graph_input_state
from app.agents.kb_chat_graph import build_kb_chat_graph
from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.api.sse import SseHeartbeatStats
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.core.memory_store import StoreManager
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.llm_client import LLMClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.redis_client import RedisClient
from app.integrations.rerank_client import RerankClient
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_session import ChatSession
from app.prompts import get_prompt_loader
from app.schemas.chats import KbChatConfig
from app.services import kb_chat_service_answer_stream_cached as kb_cached
from app.services import kb_chat_service_answer_stream_postprocess as kb_post
from app.services.context_builder import ContextBuilder
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.kb_chat_service_contracts import _KbChatStreamRunState, _as_str_dict
from app.services.kb_chat_service_method_bindings import bind_kb_chat_service_methods
from app.services.retrieval_service import RetrievalService
from app.services.semantic_cache.service import KbChatSemanticCacheService
from app.services.streaming import StreamState, apply_updates_chunk, extract_stream_delta
from app.services import kb_chat_service_execution as kb_execution
from app.agents.kb_chat_contracts import KB_CHAT_CUSTOM_EVENT_TYPES
from app.services import kb_chat_service_schema as kb_schema


class KbChatService:
    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
        milvus: MilvusClient,
        embedding: EmbeddingClient,
        reranker: RerankClient | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._embedding = embedding
        self._settings = get_settings()
        self._retrieval = RetrievalService(
            db, milvus, embedding, redis, reranker=reranker
        )
        self._context_builder = ContextBuilder(self._settings)
        self._summary_service = ConversationSummaryService(db, settings=self._settings)
        self._prompts = get_prompt_loader()
        self._semantic_cache_service = KbChatSemanticCacheService(
            embedding=embedding,
            settings=self._settings,
        )

    def _build_graph(
        self,
        *,
        chat_model: Any,
        tools: list,
        tool_meta_by_name: dict,
        kb_chat_config: KbChatConfig,
    ) -> KbChatAgenticGraph:
        """构建 KB Chat 图（agentic RAG 流程，已移除 legacy 实现）。"""
        return build_kb_chat_graph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            kb_chat_config=kb_chat_config.model_dump(mode="json"),
        )

    async def get_graph_schema(
        self: Any,
        *,
        kb_chat_config: KbChatConfig | None = None,
        selected_kb_ids: list[Any] | None = None,
    ) -> dict[str, Any]:
        return await kb_schema.get_graph_schema(
            self,
            kb_chat_config=kb_chat_config,
            selected_kb_ids=selected_kb_ids,
        )

    async def answer_stream(
        self: Any,
        *,
        session: ChatSession,
        user_content: str,
        request: object | None = None,
        run: AgentRun | None = None,
        sse_heartbeat_stats: SseHeartbeatStats | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """处理用户问题并返回流式 SSE（状态与节点事件基于 LangGraph 原生流）。"""
        if run is None:
            cached_events = await kb_cached._maybe_build_cached_stream_events(
                self,
                session=session,
                user_content=user_content,
            )
            if cached_events is not None:
                for event_name, payload in cached_events:
                    yield (event_name, payload)
                return
        else:
            await kb_execution._ensure_kb_chat_resume_target_valid(
                self,
                session=session,
                run=run,
            )

        exec_ctx = await kb_execution._prepare_kb_chat_execution(
            self,
            session=session,
            user_content=user_content,
            run=run,
        )
        run = exec_ctx.run
        graph_task: asyncio.Task | None = None
        disconnect_task: asyncio.Task | None = None

        stream_state = StreamState(
            messages=list(exec_ctx.state.get("messages") or []),
            pending_tool_calls=list(exec_ctx.state.get("pending_tool_calls") or []),
            stage_summaries=dict(exec_ctx.state.get("stage_summaries") or {}),
            metrics=dict(exec_ctx.state.get("metrics") or {}),
            loop_counts=dict(exec_ctx.state.get("loop_counts") or {}),
        )
        protocol_emit_total = 0
        protocol_drift_total = 0
        protocol_salvage_total = 0
        node_io_snapshot_truncated_count = 0
        custom_event_unhandled_count = 0
        stream_run_state = _KbChatStreamRunState(stage_status={}, stage_attempts={})
        last_good_answer: str | None = None
        last_good_answer_source: str | None = None

        def _emit_enveloped(
            *,
            event_type: str,
            payload: dict[str, Any],
            node_name: str | None = None,
            node_path: list[str] | None = None,
            attempt: int | None = None,
        ) -> tuple[str, dict[str, Any]]:
            event_seq["value"] += 1
            seq = event_seq["value"]
            nonlocal protocol_emit_total
            nonlocal protocol_drift_total
            nonlocal protocol_salvage_total
            protocol_emit_total += 1
            resolved_node_name = (
                node_name if isinstance(node_name, str) and node_name else None
            )
            drift_delta = 0
            salvage_used = False
            if event_type in {"messages", "updates", "node_io", "step"}:
                if (
                    resolved_node_name is None
                    and isinstance(node_path, list)
                    and node_path
                ):
                    resolved_node_name = node_path[-1]
                    drift_delta += 1
                    salvage_used = True
            scoped_node_path = self._build_scoped_node_path(
                node_name=resolved_node_name,
                node_path=node_path,
            )
            if (
                not isinstance(payload.get("ts"), str)
                or not str(payload.get("ts") or "").strip()
            ):
                drift_delta += 1
                salvage_used = True
            protocol_drift_total += drift_delta
            if salvage_used:
                protocol_salvage_total += 1
            node = None
            if resolved_node_name is not None:
                node = {"id": resolved_node_name, "name": resolved_node_name}
            emitted_payload = self._build_protocol_event_payload(
                event_type=event_type,
                run_id=run.id,
                payload=payload,
                node=node,
                event_id=f"{run.id}:{seq}",
                seq=seq,
                node_path=scoped_node_path,
                attempt=attempt,
            )
            return (
                event_type,
                emitted_payload,
            )

        def _emit_state(
            *,
            run_status: str,
            message: str | None = None,
            degrade_reason_value: str | None = None,
            current_step_status_override: str | None = None,
            node_path: list[str] | None = None,
        ) -> tuple[str, dict[str, Any]]:
            stream_run_state.state_version += 1
            payload = self._build_stream_state_payload(
                run_id=run.id,
                run_status=run_status,
                current_step_id=stream_run_state.current_step_id,
                current_node=stream_run_state.current_node,
                stage_status=stream_run_state.stage_status,
                stage_attempts=stream_run_state.stage_attempts,
                state_version=stream_run_state.state_version,
                active_path=self._build_active_path(
                    stage_status=stream_run_state.stage_status,
                    current_step_id=stream_run_state.current_step_id,
                ),
                last_good_answer=last_good_answer,
                degrade_reason=degrade_reason_value,
                message=message,
                current_step_status_override=current_step_status_override,
            )
            event_attempt = (
                payload.get("attempt")
                if isinstance(payload.get("attempt"), int)
                else None
            )
            return _emit_enveloped(
                event_type="state",
                payload=payload,
                node_path=node_path or [],
                attempt=event_attempt,
            )

        def _emit_ui_event(
            *,
            event_type: str,
            message: str | None = None,
            candidate_answer: str | None = None,
            source_step_id: str | None = None,
            degrade_reason_value: str | None = None,
        ) -> tuple[str, dict[str, Any]]:
            payload: dict[str, Any] = {
                "event_type": event_type,
                "run_id": str(run.id),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if message is not None:
                payload["message"] = message
            if candidate_answer is not None:
                payload["candidate_answer"] = candidate_answer
            if source_step_id is not None:
                payload["source_step_id"] = source_step_id
            if degrade_reason_value is not None:
                payload["degrade_reason"] = degrade_reason_value
            return _emit_enveloped(event_type="ui_event", payload=payload)

        async def _cancel_graph() -> None:
            if graph_task is None or graph_task.done():
                return
            graph_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await graph_task

        try:
            event_seq = {"value": 0}
            yield (
                "meta",
                self._build_protocol_event_payload(
                    event_type="meta",
                    run_id=run.id,
                    payload={
                        "run_id": str(run.id),
                        "session_id": str(session.id),
                        "session_type": session.session_type.value,
                        "thread_id": exec_ctx.thread_id,
                        "mode": session.mode.value,
                    },
                    event_id=f"{run.id}:0",
                    seq=0,
                ),
            )
            yield _emit_state(
                run_status=AgentRunStatus.RUNNING.value,
                message="知识库问答开始",
            )

            compiled = exec_ctx.compiled_graph
            if compiled is None:
                store = None
                try:
                    store = StoreManager.get_store()
                except Exception:
                    store = None
                compiled = exec_ctx.graph.compile(
                    checkpointer=CheckpointManager.get_checkpointer(),
                    store=store,
                )
            config = exec_ctx.graph.make_run_config(thread_id=exec_ctx.thread_id)
            if exec_ctx.resume_checkpoint_id is not None:
                configurable = _as_str_dict(config.get("configurable"))
                configurable["checkpoint_id"] = exec_ctx.resume_checkpoint_id
                config = {**config, "configurable": configurable}
            stream = compiled.astream(
                build_graph_input_state(exec_ctx.state),
                cast(RunnableConfig, config),
                context=exec_ctx.run_context,
                **self._build_graph_stream_options(),
            )

            queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
            disconnect_event = asyncio.Event()

            async def _run_graph() -> None:
                try:
                    async for raw_event in stream:
                        normalized = self._normalize_graph_stream_event(raw_event)
                        if normalized is None:
                            continue
                        await queue.put(("event", normalized))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await queue.put(("error", exc))
                finally:
                    await queue.put(("done", None))
                    try:
                        stream_aclose = getattr(stream, "aclose", None)
                        if callable(stream_aclose):
                            await cast(Awaitable[None], stream_aclose())
                    except Exception:
                        pass

            async def _monitor_disconnect() -> None:
                if request is None:
                    return
                is_disconnected = getattr(request, "is_disconnected", None)
                if not callable(is_disconnected):
                    return
                disconnect_checker = cast(
                    Callable[[], Awaitable[bool]],
                    is_disconnected,
                )
                while True:
                    if await disconnect_checker():
                        disconnect_event.set()
                        return
                    await asyncio.sleep(0.2)

            graph_task = asyncio.create_task(_run_graph())
            disconnect_task = (
                asyncio.create_task(_monitor_disconnect())
                if request is not None
                else None
            )

            while True:
                if disconnect_event.is_set():
                    await _cancel_graph()
                    await self._persist_guardrail_run(
                        exec_ctx=exec_ctx,
                        run=run,
                        status=AgentRunStatus.FAILED,
                        reason="errterm_client_disconnect",
                        stream_state=stream_state,
                    )
                    self._release_retrieval_buffer(exec_ctx)
                    yield _emit_state(
                        run_status=AgentRunStatus.FAILED.value,
                        message="client disconnected before stream completed",
                        current_step_status_override=AgentRunStatus.FAILED.value,
                    )
                    yield (
                        "error",
                        {
                            "code": "CHAT_STREAM_TERMINATED",
                            "message": "client disconnected before stream completed",
                        },
                    )
                    return

                queue_task = asyncio.create_task(queue.get())
                wait_tasks = {queue_task}
                if disconnect_task is not None:
                    wait_tasks.add(disconnect_task)
                done, _pending = await asyncio.wait(
                    wait_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if disconnect_task is not None and disconnect_task in done:
                    if disconnect_event.is_set():
                        if not queue_task.done():
                            queue_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await queue_task
                        await _cancel_graph()
                        await self._persist_guardrail_run(
                            exec_ctx=exec_ctx,
                            run=run,
                            status=AgentRunStatus.FAILED,
                            reason="errterm_client_disconnect",
                            stream_state=stream_state,
                        )
                        self._release_retrieval_buffer(exec_ctx)
                        yield _emit_state(
                            run_status=AgentRunStatus.FAILED.value,
                            message="client disconnected before stream completed",
                            current_step_status_override=AgentRunStatus.FAILED.value,
                        )
                        yield (
                            "error",
                            {
                                "code": "CHAT_STREAM_TERMINATED",
                                "message": "client disconnected before stream completed",
                            },
                        )
                        return
                    disconnect_task = None

                if queue_task not in done:
                    continue

                kind, payload = queue_task.result()
                if kind == "event":
                    if not isinstance(payload, tuple) or len(payload) != 3:
                        continue
                    mode, chunk, node_path = payload

                    if mode == "messages":
                        token = None
                        token_meta: dict[str, Any] | None = None
                        if isinstance(chunk, tuple) and len(chunk) == 2:
                            token = chunk[0]
                            if isinstance(chunk[1], dict):
                                token_meta = chunk[1]
                        elif isinstance(chunk, list) and len(chunk) == 2:
                            token = chunk[0]
                            if isinstance(chunk[1], dict):
                                token_meta = chunk[1]
                        else:
                            token = chunk

                        deltas = extract_stream_delta(
                            token,
                            token_meta,
                        )
                        if deltas:
                            node_name = (
                                token_meta.get("langgraph_node")
                                if isinstance(token_meta, dict)
                                and isinstance(token_meta.get("langgraph_node"), str)
                                else None
                            )
                            if (
                                node_name is None
                                and isinstance(node_path, list)
                                and node_path
                            ):
                                node_name = node_path[-1]
                            yield _emit_enveloped(
                                event_type="messages",
                                payload={
                                    "run_id": str(run.id),
                                    "node": node_name,
                                    "deltas": [delta.to_dict() for delta in deltas],
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                },
                                node_name=node_name,
                                node_path=node_path or [],
                            )
                        continue

                    if mode == "updates" and isinstance(chunk, dict):
                        candidate_node = next(
                            (
                                source
                                for source in chunk.keys()
                                if isinstance(source, str) and source != "__interrupt__"
                            ),
                            None,
                        )
                        if (
                            candidate_node is None
                            and isinstance(node_path, list)
                            and node_path
                        ):
                            candidate_node = node_path[-1]
                        interrupts = apply_updates_chunk(stream_state, chunk)
                        candidate, candidate_source = self._extract_last_good_answer(
                            answer="",
                            stream_state=stream_state,
                        )
                        if candidate:
                            last_good_answer = candidate
                            last_good_answer_source = candidate_source
                        self._ensure_no_pending_tool_approval(
                            pending_tool_calls=stream_state.pending_tool_calls,
                            interrupts=interrupts,
                        )
                        yield _emit_enveloped(
                            event_type="updates",
                            payload={
                                "run_id": str(run.id),
                                "chunk": chunk,
                                "ts": datetime.now(timezone.utc).isoformat(),
                            },
                            node_name=candidate_node,
                            node_path=node_path or [],
                        )
                        continue

                    if mode == "tasks" and isinstance(chunk, dict):
                        step_payload = self._build_step_payload_from_task_event(
                            payload=chunk,
                            node_path=node_path,
                        )
                        if step_payload is None:
                            continue
                        node_name = self._apply_stream_state_step(
                            stream_state=stream_run_state,
                            payload=step_payload,
                            node_path=node_path,
                        )
                        event_attempt = (
                            stream_run_state.stage_attempts.get(node_name)
                            if isinstance(node_name, str) and node_name
                            else None
                        )
                        yield _emit_enveloped(
                            event_type="step",
                            payload=step_payload,
                            node_name=node_name,
                            node_path=node_path or [],
                            attempt=event_attempt
                            if isinstance(event_attempt, int)
                            else None,
                        )
                        yield _emit_state(
                            run_status=AgentRunStatus.RUNNING.value,
                            message=(
                                step_payload.get("message")
                                if isinstance(step_payload.get("message"), str)
                                else None
                            ),
                            node_path=node_path or [],
                        )
                        continue

                    if mode == "custom":
                        safe_payload = self._json_safe_custom_payload(chunk)
                        if isinstance(safe_payload, dict):
                            node_name = (
                                safe_payload.get("node_name")
                                if isinstance(safe_payload.get("node_name"), str)
                                else None
                            )
                            payload_dict = dict(safe_payload)
                            payload_dict.setdefault("run_id", str(run.id))
                            payload_dict.setdefault(
                                "ts", datetime.now(timezone.utc).isoformat()
                            )
                            custom_event_type = (
                                payload_dict.get("event_type")
                                if isinstance(payload_dict.get("event_type"), str)
                                else "custom"
                            )
                            if custom_event_type not in KB_CHAT_CUSTOM_EVENT_TYPES:
                                custom_event_unhandled_count += 1
                            emitted_event_type = (
                                "node_io"
                                if custom_event_type == "node_io"
                                else "custom"
                            )
                            event_attempt = (
                                payload_dict.get("attempt")
                                if isinstance(payload_dict.get("attempt"), int)
                                else None
                            )
                            if custom_event_type == "node_io":
                                node_name = self._apply_stream_state_node_io(
                                    stream_state=stream_run_state,
                                    payload=payload_dict,
                                    node_path=node_path,
                                )
                                execution_id = self._resolve_stream_execution_id(
                                    stream_state=stream_run_state,
                                    payload=payload_dict,
                                    node_name=node_name,
                                    node_path=node_path,
                                )
                                if execution_id is not None:
                                    payload_dict["execution_id"] = execution_id
                                    payload_dict.setdefault("task_id", execution_id)
                                    self._remember_stream_execution(
                                        stream_state=stream_run_state,
                                        execution_id=execution_id,
                                        node_name=node_name,
                                        node_path=node_path,
                                    )
                                for meta_key in (
                                    "input_snapshot_meta",
                                    "output_snapshot_meta",
                                ):
                                    meta = payload_dict.get(meta_key)
                                    if (
                                        isinstance(meta, dict)
                                        and meta.get("truncated") is True
                                    ):
                                        node_io_snapshot_truncated_count += 1
                            yield _emit_enveloped(
                                event_type=emitted_event_type,
                                payload=payload_dict,
                                node_name=node_name,
                                node_path=node_path or [],
                                attempt=event_attempt,
                            )
                            if custom_event_type == "node_io" and node_name is not None:
                                error_message = (
                                    payload_dict.get("error_summary")
                                    if payload_dict.get("phase") == "error"
                                    and isinstance(
                                        payload_dict.get("error_summary"), str
                                    )
                                    else None
                                )
                                yield _emit_state(
                                    run_status=AgentRunStatus.RUNNING.value,
                                    message=error_message,
                                    node_path=node_path or [],
                                )
                        continue

                    continue

                if kind == "error":
                    if isinstance(payload, BaseException):
                        raise payload
                    raise RuntimeError("KB Chat graph stream failed without exception payload")
                if kind == "done":
                    break

            self._ensure_no_pending_tool_approval(
                pending_tool_calls=stream_state.pending_tool_calls,
                interrupts=None,
            )

            async for event_name, payload in kb_post._postprocess_live_stream(
                self,
                session=session,
                exec_ctx=exec_ctx,
                run=run,
                stream_state=stream_state,
                stream_run_state=stream_run_state,
                sse_heartbeat_stats=sse_heartbeat_stats,
                protocol_emit_total=protocol_emit_total,
                protocol_drift_total=protocol_drift_total,
                protocol_salvage_total=protocol_salvage_total,
                node_io_snapshot_truncated_count=node_io_snapshot_truncated_count,
                custom_event_unhandled_count=custom_event_unhandled_count,
                last_good_answer=last_good_answer,
                last_good_answer_source=last_good_answer_source,
                _emit_enveloped=_emit_enveloped,
                _emit_state=_emit_state,
                _emit_ui_event=_emit_ui_event,
            ):
                yield (event_name, payload)
        except asyncio.CancelledError:
            await _cancel_graph()
            await self._persist_guardrail_run(
                exec_ctx=exec_ctx,
                run=run,
                status=AgentRunStatus.FAILED,
                reason="errterm_cancelled",
                stream_state=stream_state,
            )
            self._release_retrieval_buffer(exec_ctx)
            raise
        except Exception as e:
            await _cancel_graph()
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            error_summary = e.message if isinstance(e, AppError) else str(e)
            run.error_message = error_summary
            run.stage_summaries = {
                **(
                    run.stage_summaries if isinstance(run.stage_summaries, dict) else {}
                ),
                "errterm": {
                    "reason": "stream_exception",
                    "message": error_summary,
                    "at": (
                        error_finished_at.isoformat()
                        if (error_finished_at := run.finished_at) is not None
                        else None
                    ),
                },
            }
            await self._db.commit()
            self._release_retrieval_buffer(exec_ctx)
            yield _emit_state(
                run_status=AgentRunStatus.FAILED.value,
                message=error_summary,
                degrade_reason_value=error_summary,
                current_step_status_override=AgentRunStatus.FAILED.value,
            )
            if isinstance(e, AppError):
                yield (
                    "error",
                    {
                        "code": e.code,
                        "message": e.message,
                        "details": e.details,
                    },
                )
                return
            yield (
                "error",
                {
                    "code": "CHAT_STREAM_FAILED",
                    "message": str(e),
                },
            )
        finally:
            if disconnect_task is not None:
                disconnect_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await disconnect_task
            set_run_id(None)



bind_kb_chat_service_methods(KbChatService)