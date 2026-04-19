from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.agent_run import AgentRunStatus
from app.models.chat_session import ChatSession


async def _maybe_build_cached_stream_events(
    self,
    *,
    session: ChatSession,
    user_content: str,
) -> tuple[list[tuple[str, Any]] | None, list[float] | None]:
    await self._ensure_no_running_kb_chat_run(session_id=session.id)
    cache_config = self._resolve_session_kb_chat_config(session)
    cache_hit, question_vector = await self._semantic_cache_lookup(
        session=session,
        kb_chat_config=cache_config,
        question=user_content,
    )
    if cache_hit is None:
        return None, question_vector

    cached_response = await self._persist_semantic_cache_hit(
        session=session,
        user_content=user_content,
        cache_hit=cache_hit,
    )
    cached_running_stage_status = {"semantic_cache": "started"}
    cached_succeeded_stage_status = {"semantic_cache": "completed"}
    cached_stage_attempts: dict[str, int] = {}
    run_payload = cached_response.run.model_dump(mode="json")
    return [
        (
            "meta",
            self._build_protocol_event_payload(
                event_type="meta",
                run_id=cached_response.run.id,
                payload={
                    "run_id": str(cached_response.run.id),
                    "session_id": str(session.id),
                    "session_type": session.session_type.value,
                    "thread_id": str(session.id),
                    "mode": session.mode.value,
                    "source": "cached",
                },
                event_id=f"{cached_response.run.id}:0",
                seq=0,
            ),
        ),
        (
            "state",
            self._build_protocol_event_payload(
                event_type="state",
                run_id=cached_response.run.id,
                payload=self._build_stream_state_payload(
                    run_id=cached_response.run.id,
                    run_status=AgentRunStatus.RUNNING.value,
                    current_step_id="semantic_cache",
                    current_node="semantic_cache",
                    stage_status=cached_running_stage_status,
                    stage_attempts=cached_stage_attempts,
                    state_version=1,
                    active_path=self._build_active_path(
                        stage_status=cached_running_stage_status,
                        current_step_id="semantic_cache",
                    ),
                    message="语义缓存命中，直接返回缓存答案",
                ),
                event_id=f"{cached_response.run.id}:1",
                seq=1,
            ),
        ),
        *list(
            self._emit_semantic_cache_fast_path(
                run_id=cached_response.run.id,
                cache_meta=cached_response.cache,
                start_seq=2,
            )
        ),
        (
            "stream_end",
            self._build_protocol_event_payload(
                event_type="stream_end",
                run_id=cached_response.run.id,
                payload={
                    "run_id": str(cached_response.run.id),
                    "source": "cached",
                    "terminal_candidate": "out200",
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
                event_id=f"{cached_response.run.id}:4",
                seq=4,
            ),
        ),
        (
            "state",
            self._build_protocol_event_payload(
                event_type="state",
                run_id=cached_response.run.id,
                payload=self._build_stream_state_payload(
                    run_id=cached_response.run.id,
                    run_status=AgentRunStatus.SUCCEEDED.value,
                    current_step_id="semantic_cache",
                    current_node="semantic_cache",
                    stage_status=cached_succeeded_stage_status,
                    stage_attempts=cached_stage_attempts,
                    state_version=2,
                    active_path=self._build_active_path(
                        stage_status=cached_succeeded_stage_status,
                        current_step_id="semantic_cache",
                    ),
                    current_step_status_override=AgentRunStatus.SUCCEEDED.value,
                ),
                event_id=f"{cached_response.run.id}:5",
                seq=5,
            ),
        ),
        (
            "final",
            self._build_terminal_event_payload(
                status=cached_response.status,
                run_payload=run_payload,
                assistant_message=cached_response.assistant_message.model_dump(
                    mode="json"
                ),
                evidence=[item.model_dump(mode="json") for item in cached_response.evidence],
                stage_summaries=(
                    cached_response.stage_summaries
                    if isinstance(cached_response.stage_summaries, dict)
                    else None
                ),
                metrics=(
                    cached_response.metrics
                    if isinstance(cached_response.metrics, dict)
                    else None
                ),
                source=cached_response.source,
                cache=(
                    cached_response.cache.model_dump(mode="json")
                    if cached_response.cache is not None
                    else None
                ),
            ),
        ),
    ], None
