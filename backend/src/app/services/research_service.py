"""Research session orchestration service。"""

from __future__ import annotations

import inspect
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import bad_request, not_found
from app.core.settings import Settings, get_settings
from app.models.research_artifact import ResearchArtifact
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.models.research_task_outbox import (
    RESEARCH_SESSION_TASK_NAME,
    ResearchTaskOutbox,
    ResearchTaskOutboxStatus,
)
from app.schemas.research import (
    ResearchArtifactsResponse,
    ResearchClarificationRequest,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchSessionCreateRequest,
)
from app.services import research_service_session_ops
from app.services.research_artifact_store import ResearchArtifactStore
from app.services.research_event_store import ResearchEventStore
from app.services.research_finalizer import ResearchFinalizer, ResearchFinalizerResult
from app.services.research_observability import (
    build_failure_metrics as build_failure_metrics,  # noqa: F401
    build_research_gate_thresholds,
    build_research_metrics as build_research_metrics,  # noqa: F401
    classify_research_fault as classify_research_fault,  # noqa: F401
    ensure_research_trace_id,
    evaluate_research_gate as evaluate_research_gate,  # noqa: F401
)
from app.services.research_planner import ResearchPlanner
from app.services.research_planner_types import ResearchPlannerResult
from app.services.research_replay import (
    evaluate_research_replay_consistency as evaluate_research_replay_consistency,  # noqa: F401
)
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_runtime_types import (
    ResearchPlanProgressUpdate,
    ResearchRuntimeActivityUpdate,
)
from app.services.research_service_contracts import (
    build_artifacts_response as build_research_artifacts_response,
    build_event_envelopes,
    build_plan_progress_snapshot,
    build_plan_progress_summary,
    extract_plan_progress_position,
    lc_agent_name_for_phase,
    normalize_plan_progress_index,
    normalize_plan_progress_message,
    plan_progress_snapshot_equals,
)
from app.services.research_service_execution import (
    append_trace_events,
    merge_runtime_projection_snapshot,
    persist_metrics_artifacts,
    persist_runtime_activity_update,
    persist_runtime_context_artifacts,
    persist_runtime_execution_artifacts,
    read_committed_session_status,
    read_json_artifact,
    runtime_live_board_updated_at,
)
from app.services.research_service_runtime import (
    ResearchRuntimeRunner,
    UnconfiguredResearchRuntimeRunner,
)
from app.services.research_workspace_files import build_workspace_bootstrap_artifacts

PLAN_PROGRESS_ARTIFACT_KEY = "plan_progress_snapshot"
PLAN_PROGRESS_EVENT_TYPE = "research.plan_progress.updated"
RUNTIME_TASK_GRAPH_ARTIFACT_KEY = "runtime_task_graph_json"
RUNTIME_LIVE_BOARD_ARTIFACT_KEY = "runtime_live_board_json"
class ResearchService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        planner: ResearchPlanner,
        runtime_runner: ResearchRuntimeRunner,
        finalizer: ResearchFinalizer,
        event_store: ResearchEventStore | None = None,
        artifact_store: ResearchArtifactStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._planner = planner
        self._runtime_runner = runtime_runner
        self._finalizer = finalizer
        self._event_store = event_store or ResearchEventStore(db)
        self._artifact_store = artifact_store or ResearchArtifactStore(db)
        self._settings = settings or get_settings()
        self._gate_thresholds = build_research_gate_thresholds(self._settings)

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        stmt = (
            select(ResearchSession)
            .where(ResearchSession.id == session_id)
            .options(
                selectinload(ResearchSession.artifacts),
                selectinload(ResearchSession.events),
                selectinload(ResearchSession.task_outbox_entries),
            )
        )
        session = (await self._db.execute(stmt)).scalar_one_or_none()
        if session is None:
            raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")
        return session

    def read_plan_snapshot(self, session: ResearchSession) -> ResearchPlanSnapshot:
        artifact = self._artifact_by_key(session, "plan_snapshot")
        payload = artifact.content_json
        if not isinstance(payload, dict):
            raise bad_request(
                code="RESEARCH_PLAN_SNAPSHOT_MISSING",
                message="研究计划快照不存在或格式无效",
            )
        return ResearchPlanSnapshot.model_validate(payload)

    def _read_plan_progress_payload(
        self, session: ResearchSession
    ) -> dict[str, object] | None:
        artifact = next(
            (
                item
                for item in session.artifacts
                if item.artifact_key == PLAN_PROGRESS_ARTIFACT_KEY
            ),
            None,
        )
        payload = artifact.content_json if artifact is not None else None
        return payload if isinstance(payload, dict) else None

    def _try_read_plan_snapshot(
        self, session: ResearchSession
    ) -> ResearchPlanSnapshot | None:
        artifact = next(
            (item for item in session.artifacts if item.artifact_key == "plan_snapshot"),
            None,
        )
        payload = artifact.content_json if artifact is not None else None
        if not isinstance(payload, dict):
            return None
        return ResearchPlanSnapshot.model_validate(payload)

    async def create_session(
        self,
        request: ResearchSessionCreateRequest,
        *,
        thread_id: str,
        session_id: uuid.UUID | None = None,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        session = ResearchSession(
            id=session_id,
            thread_id=thread_id,
            question=request.question,
            status=ResearchSessionStatus.CREATED,
            planner_phase="preflight",
        )
        self._db.add(session)
        await self._db.flush()
        ensure_research_trace_id(session)

        session.transition_to(ResearchSessionStatus.PLANNING)
        plan_result = await self._planner.build_plan(request)
        if plan_result.clarification_request is not None:
            await self._persist_clarification_request(
                session=session,
                clarification_request=plan_result.clarification_request,
            )
            session.transition_to(ResearchSessionStatus.CLARIFYING)
            return session, plan_result

        if plan_result.plan_snapshot is None:
            raise bad_request(
                code="RESEARCH_PLAN_SNAPSHOT_MISSING",
                message="研究计划快照缺失",
            )
        await self._persist_planned_session_artifacts(
            session=session,
            plan_result=plan_result,
        )
        await self._event_store.append(
            session=session,
            event_type="research.plan.ready",
            phase="planner",
            payload={
                **(
                    plan_result.artifact_payload
                    if isinstance(plan_result.artifact_payload, dict)
                    else {}
                ),
                "lc_agent_name": "planner",
                "decision_source": "llm_scoper",
                "auto_start": False,
            },
            trace_id=session.trace_id,
        )
        session.transition_to(plan_result.next_status)
        self._ensure_dispatch_outbox(session=session)
        return session, plan_result

    async def _persist_clarification_request(
        self,
        *,
        session: ResearchSession,
        clarification_request: ResearchClarificationRequest,
    ) -> None:
        payload = clarification_request.model_dump(mode="json")
        await self._artifact_store.upsert(
            session=session,
            artifact_key="clarification_request",
            content_json=payload,
        )
        await self._event_store.append(
            session=session,
            event_type="research.clarification.requested",
            phase="planner",
            payload=payload,
            trace_id=session.trace_id,
        )

    async def _persist_clarification_answer(
        self,
        *,
        session: ResearchSession,
        answer: str,
    ) -> None:
        await self._artifact_store.upsert(
            session=session,
            artifact_key="clarification_answer",
            content_text=answer,
        )

    async def _persist_planned_session_artifacts(
        self,
        *,
        session: ResearchSession,
        plan_result: ResearchPlannerResult,
    ) -> None:
        plan_snapshot = plan_result.plan_snapshot
        if plan_snapshot is None:
            raise bad_request(
                code="RESEARCH_PLAN_SNAPSHOT_MISSING",
                message="研究计划快照缺失",
            )
        await self._artifact_store.upsert(
            session=session,
            artifact_key=plan_result.plan_artifact_key,
            content_json=plan_result.artifact_payload,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key="research_brief",
            content_text=plan_snapshot.research_brief,
        )
        await self._artifact_store.upsert(
            session=session,
            artifact_key=PLAN_PROGRESS_ARTIFACT_KEY,
            content_json=build_plan_progress_snapshot(
                plan_snapshot,
                current_step_index=None,
                completed_step_count=0,
            ),
        )
        bootstrap_artifacts = build_workspace_bootstrap_artifacts(
            session_id=session.id,
            question=session.question,
            plan_snapshot=plan_snapshot,
        )
        for seed in bootstrap_artifacts.values():
            await self._artifact_store.upsert(
                session=session,
                artifact_key=seed.artifact_key,
                content_text=seed.content_text,
                content_json=seed.content_json,
            )

    async def _persist_runtime_context_artifacts(
        self,
        *,
        session: ResearchSession,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> None:
        await persist_runtime_context_artifacts(
            artifact_store=self._artifact_store,
            session=session,
            runtime_context_snapshot=runtime_context_snapshot,
            task_graph_artifact_key=RUNTIME_TASK_GRAPH_ARTIFACT_KEY,
            live_board_artifact_key=RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
        )

    def _merge_runtime_projection_snapshot(
        self,
        *,
        session: ResearchSession,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> ResearchRuntimeContextSnapshot | None:
        live_board_projection = read_json_artifact(
            session,
            RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
        )
        return merge_runtime_projection_snapshot(
            live_board_projection=live_board_projection
            if isinstance(live_board_projection, dict)
            else None,
            runtime_context_snapshot=runtime_context_snapshot,
        )

    async def _persist_runtime_execution_artifacts(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> None:
        await persist_runtime_execution_artifacts(
            artifact_store=self._artifact_store,
            session=session,
            plan_snapshot=plan_snapshot,
            task_graph_artifact_key=RUNTIME_TASK_GRAPH_ARTIFACT_KEY,
            live_board_artifact_key=RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
        )

    async def _persist_runtime_activity_update(
        self,
        *,
        session: ResearchSession,
        update: ResearchRuntimeActivityUpdate,
    ) -> dict[str, object]:
        return await persist_runtime_activity_update(
            artifact_store=self._artifact_store,
            session=session,
            update=update,
            live_board_artifact_key=RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
        )

    async def submit_clarification(
        self,
        *,
        session: ResearchSession,
        answer: str,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        return await research_service_session_ops.submit_clarification(
            self,
            session=session,
            answer=answer,
        )

    async def update_plan(
        self,
        *,
        session: ResearchSession,
        feedback: str,
    ) -> tuple[ResearchSession, ResearchPlannerResult]:
        return await research_service_session_ops.update_plan(
            self,
            session=session,
            feedback=feedback,
        )

    async def start_session(self, *, session: ResearchSession) -> ResearchSession:
        return await research_service_session_ops.start_session(
            self,
            session=session,
        )

    async def stop_session(
        self,
        *,
        session: ResearchSession,
        reason: str | None = None,
    ) -> ResearchSession:
        return await research_service_session_ops.stop_session(
            self,
            session=session,
            reason=reason,
        )

    @staticmethod
    def _build_effective_planning_question(
        *,
        session: ResearchSession,
        answer: str,
    ) -> str:
        normalized_question = str(session.question or "").strip()
        clarification_questions: list[str] = []
        clarification_answers: list[str] = []
        for event in sorted(session.events, key=lambda item: item.sequence):
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.event_type == "research.clarification.requested":
                summary = str(payload.get("summary") or "").strip()
                if summary:
                    clarification_questions.append(f"- 摘要：{summary}")
                raw_questions = payload.get("questions")
                if not isinstance(raw_questions, list):
                    continue
                for item in raw_questions:
                    if not isinstance(item, dict):
                        continue
                    question_id = str(item.get("id") or "").strip()
                    question_text = str(item.get("question") or "").strip()
                    why_it_matters = str(item.get("why_it_matters") or "").strip()
                    fragments = [fragment for fragment in (question_id, question_text) if fragment]
                    if not fragments:
                        continue
                    line = "- " + " ".join(fragments)
                    if why_it_matters:
                        line += f" | 影响：{why_it_matters}"
                    clarification_questions.append(line)
                continue

            if event.event_type != "research.clarification.submitted":
                continue
            raw_answer = payload.get("answer")
            if isinstance(raw_answer, str) and raw_answer.strip():
                clarification_answers.append(f"- {raw_answer.strip()}")

        normalized_answer = str(answer or "").strip()
        current_round = len(clarification_answers) + (1 if normalized_answer else 0)
        sections = [f"原始问题：\n{normalized_question or '未提供'}"]
        if clarification_questions:
            sections.append(
                "已发出的澄清问题：\n" + "\n".join(clarification_questions)
            )
        if clarification_answers:
            sections.append(
                "已收到的澄清回答：\n" + "\n".join(clarification_answers)
            )
        if normalized_answer:
            sections.append(f"本轮补充：\n- {normalized_answer}")
        sections.append(
            "规划策略：\n"
            "- 首轮澄清应尽量一次性收齐会改变研究路径的关键缺口。\n"
            "- 若当前已经收到至少 1 轮用户补充，默认直接生成研究计划；只有在研究对象、核心范围或主比较对象仍缺失到无法规划时，才允许最后一次聚合追问。\n"
            "- 时间范围、受众、输出形态等轻微模糊请采用保守假设，并写入 research_brief 或 budget_guidance。\n"
            f"- 当前澄清回答轮次：{current_round}。"
        )
        return "\n\n".join(section for section in sections if section.strip())

    @staticmethod
    def _clarification_submission_count(session: ResearchSession) -> int:
        count = 0
        for event in session.events:
            if event.event_type == "research.clarification.submitted":
                count += 1
        return count

    @classmethod
    def _should_allow_follow_up_clarification(
        cls,
        *,
        session: ResearchSession,
        answer: str,
    ) -> bool:
        del answer
        submission_count = cls._clarification_submission_count(session) + 1
        return submission_count < 2

    def _ensure_dispatch_outbox(self, *, session: ResearchSession) -> None:
        if session.status != ResearchSessionStatus.QUEUED:
            return
        existing = next(
            (
                item
                for item in session.task_outbox_entries
                if item.task_name == RESEARCH_SESSION_TASK_NAME
            ),
            None,
        )
        if existing is not None:
            if existing.status == ResearchTaskOutboxStatus.FAILED:
                existing.status = ResearchTaskOutboxStatus.PENDING
                existing.next_retry_at = None
                existing.dispatched_at = None
                existing.last_error = None
            return

        self._db.add(
            ResearchTaskOutbox(
                session_id=session.id,
                task_name=RESEARCH_SESSION_TASK_NAME,
                status=ResearchTaskOutboxStatus.PENDING,
                payload={},
            )
        )

    async def execute_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchFinalizerResult | None:
        return await research_service_session_ops.execute_session(
            self,
            session=session,
            plan_snapshot=plan_snapshot,
        )

    async def fail_session(
        self,
        *,
        session: ResearchSession,
        exc: Exception,
        phase: str,
        source_provider: str | None = None,
    ) -> ResearchSession:
        return await research_service_session_ops.fail_session(
            self,
            session=session,
            exc=exc,
            phase=phase,
            source_provider=source_provider,
        )

    def list_event_envelopes(
        self,
        session: ResearchSession,
        *,
        after_event_id: str | None = None,
    ) -> list[ResearchEventEnvelope]:
        return build_event_envelopes(
            session=session,
            after_event_id=after_event_id,
        )

    def build_artifacts_response(
        self, session: ResearchSession
    ) -> ResearchArtifactsResponse:
        return build_research_artifacts_response(
            session=session,
            events=self.list_event_envelopes(session),
        )

    async def _append_trace_events(
        self,
        *,
        session: ResearchSession,
        trace_links: list[dict[str, object]],
    ) -> None:
        await append_trace_events(
            event_store=self._event_store,
            session=session,
            trace_links=trace_links,
        )

    async def _persist_metrics_artifacts(
        self,
        *,
        session: ResearchSession,
        metrics: dict[str, object],
    ) -> None:
        await persist_metrics_artifacts(
            artifact_store=self._artifact_store,
            session=session,
            metrics=metrics,
        )

    async def _read_committed_session_status(
        self,
        *,
        session: ResearchSession,
    ) -> ResearchSessionStatus | None:
        return await read_committed_session_status(
            db=self._db,
            session=session,
        )

    @staticmethod
    def _artifact_by_key(
        session: ResearchSession, artifact_key: str
    ) -> ResearchArtifact:
        artifact = next(
            (item for item in session.artifacts if item.artifact_key == artifact_key),
            None,
        )
        if artifact is None:
            raise bad_request(
                code="RESEARCH_ARTIFACT_MISSING",
                message=f"研究工件缺失：{artifact_key}",
            )
        return artifact

    async def _persist_plan_progress_snapshot(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        phase: str,
        current_step_index: int | None,
        completed_step_count: int,
        active_step_status: str = "current",
        event_message: str | None = None,
        emit_event: bool = True,
    ) -> dict[str, object]:
        normalized_message = normalize_plan_progress_message(event_message)
        existing_payload = self._read_plan_progress_payload(session)
        snapshot = build_plan_progress_snapshot(
            plan_snapshot,
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=active_step_status,
        )
        if (
            plan_progress_snapshot_equals(existing_payload, snapshot)
            and normalized_message is None
        ):
            return existing_payload if existing_payload is not None else snapshot
        await self._artifact_store.upsert(
            session=session,
            artifact_key=PLAN_PROGRESS_ARTIFACT_KEY,
            content_json=snapshot,
        )
        summary = normalized_message or build_plan_progress_summary(snapshot)
        if emit_event:
            await self._event_store.append(
                session=session,
                event_type=PLAN_PROGRESS_EVENT_TYPE,
                phase=phase,
                payload={
                    **snapshot,
                    "summary": summary,
                    "message": normalized_message,
                    "lc_agent_name": lc_agent_name_for_phase(phase),
                },
                trace_id=session.trace_id,
            )
        return snapshot

    async def _persist_terminal_plan_progress_snapshot(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        phase: str,
        terminal_state: str,
    ) -> dict[str, object]:
        existing_payload = self._read_plan_progress_payload(session)
        current_step_index, completed_step_count = extract_plan_progress_position(
            existing_payload,
            total_steps=len(plan_snapshot.subtasks),
        )
        return await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase=phase,
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=terminal_state,
        )

    async def _advance_runtime_plan_progress(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        update: ResearchPlanProgressUpdate,
    ) -> dict[str, object]:
        total_steps = len(plan_snapshot.subtasks)
        step_index = normalize_plan_progress_index(
            update.step_index,
            total_steps=total_steps,
        )
        if step_index is None:
            raise RuntimeError(
                f"计划步骤索引超出范围: {update.step_index}/{total_steps}"
            )

        existing_payload = self._read_plan_progress_payload(session)
        _, completed_step_count = extract_plan_progress_position(
            existing_payload,
            total_steps=total_steps,
        )

        current_step_index: int | None = step_index
        active_step_status = update.status
        if update.status == "complete":
            completed_step_count = max(completed_step_count, step_index)
            current_step_index = (
                completed_step_count + 1
                if completed_step_count < total_steps
                else None
            )
            active_step_status = "current"

        snapshot = await self._persist_plan_progress_snapshot(
            session=session,
            plan_snapshot=plan_snapshot,
            phase="runtime",
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=active_step_status,
            event_message=update.message,
        )
        await self._commit_checkpoint()
        return snapshot

    def _build_runtime_plan_progress_callback(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ):
        async def _callback(update: ResearchPlanProgressUpdate) -> None:
            await self._advance_runtime_plan_progress(
                session=session,
                plan_snapshot=plan_snapshot,
                update=update,
            )

        return _callback

    def _build_runtime_activity_callback(
        self,
        *,
        session: ResearchSession,
    ):
        async def _callback(update: ResearchRuntimeActivityUpdate) -> None:
            live_board = await self._persist_runtime_activity_update(
                session=session,
                update=update,
            )
            await self._event_store.append(
                session=session,
                event_type="research.runtime.activity",
                phase="runtime",
                payload={
                    "task_id": update.task_id,
                    "title": update.title,
                    "task_kind": update.task_kind,
                    "status": update.status,
                    "parallel_group": update.parallel_group,
                    "message": update.message,
                    "summary": update.message or update.title,
                    "lc_agent_name": update.agent_name,
                    "subagent_name": update.subagent_name,
                    "current_task_label": live_board.get("current_task_label"),
                    "current_agent_label": live_board.get("current_agent_label"),
                },
                trace_id=session.trace_id,
            )
            await self._commit_checkpoint()

        return _callback

    async def _commit_checkpoint(self) -> None:
        commit = getattr(self._db, "commit", None)
        if callable(commit):
            commit_result = commit()
            if inspect.isawaitable(commit_result):
                await commit_result

def build_research_service(
    *,
    db: AsyncSession,
    runtime_runner: ResearchRuntimeRunner | None = None,
) -> ResearchService:
    return ResearchService(
        db=db,
        planner=ResearchPlanner(),
        runtime_runner=runtime_runner or UnconfiguredResearchRuntimeRunner(),
        finalizer=ResearchFinalizer(),
        settings=get_settings(),
    )
