"""Research session orchestration service。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
import inspect
import uuid
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.provider_registry import resolve_langchain_structured_output_method
from app.core.checkpoint import CheckpointManager
from app.core.errors import bad_request, not_found
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_cache import create_chat_model_cached
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.research_artifact import ResearchArtifact
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.models.research_task_outbox import (
    RESEARCH_SESSION_TASK_NAME,
    ResearchTaskOutbox,
    ResearchTaskOutboxStatus,
)
from app.repositories.research_session_repository import ResearchSessionRepository
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
from app.services.research_alignment_judge import ResearchAlignmentJudge
from app.services.research_observability import (
    ResearchRuntimeRunResult,
    build_failure_metrics as build_failure_metrics,  # noqa: F401
    build_trace_links,
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
    ResearchRuntimeActivityUpdate,
)
from app.services.research_service_contracts import (
    build_artifacts_response as build_research_artifacts_response,
    build_event_envelopes,
    build_plan_progress_snapshot,
    build_plan_progress_snapshot_from_runtime_todos,
    build_plan_progress_summary,
    extract_plan_progress_position,
    lc_agent_name_for_phase,
    normalize_plan_progress_message,
    plan_progress_snapshot_equals,
)
from app.services.research_service_execution import (
    append_trace_events,
    merge_runtime_projection_snapshot,
    persist_final_report_artifacts,
    persist_metrics_artifacts,
    persist_runtime_activity_update,
    persist_runtime_context_artifacts,
    persist_runtime_execution_artifacts,
    read_committed_session_status,
    read_json_artifact,
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
logger = logging.getLogger(__name__)
_StageResultT = TypeVar("_StageResultT")
_SESSION_SNAPSHOT_STATE_FIELDS = (
    "status",
    "planner_phase",
    "runtime_phase",
    "finalizer_phase",
    "trace_id",
    "last_event_sequence",
    "metrics",
    "error_message",
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
)
_SESSION_SNAPSHOT_RELATIONSHIP_FIELDS = (
    "events",
    "artifacts",
    "task_outbox_entries",
)


class ResearchService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        planner: ResearchPlanner,
        runtime_runner: ResearchRuntimeRunner,
        finalizer: ResearchFinalizer,
        session_repository: ResearchSessionRepository | None = None,
        event_store: ResearchEventStore | None = None,
        artifact_store: ResearchArtifactStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._sessionmaker = sessionmaker
        self._planner = planner
        self._runtime_runner = runtime_runner
        self._finalizer = finalizer
        self._session_repository = session_repository or ResearchSessionRepository(db)
        self._event_store = event_store or ResearchEventStore(db)
        self._artifact_store = artifact_store or ResearchArtifactStore(db)
        self._settings = settings or get_settings()
        self._gate_thresholds = build_research_gate_thresholds(self._settings)

    def _build_db_bound_service(self, db: AsyncSession) -> "ResearchService":
        return ResearchService(
            db=db,
            planner=self._planner,
            runtime_runner=self._runtime_runner,
            finalizer=self._finalizer,
            session_repository=ResearchSessionRepository(db),
            event_store=ResearchEventStore(db),
            artifact_store=ResearchArtifactStore(db),
            settings=self._settings,
        )

    @staticmethod
    def _copy_session_state_fields(
        *,
        source: ResearchSession,
        target: ResearchSession,
        fields: tuple[str, ...],
    ) -> None:
        for field in fields:
            value = getattr(source, field)
            if isinstance(value, dict):
                value = dict(value)
            elif isinstance(value, list):
                value = list(value)
            setattr(target, field, value)

    async def _refresh_session_snapshot(
        self,
        *,
        session: ResearchSession,
        relationship_fields: tuple[str, ...] = (),
    ) -> None:
        attribute_names: list[str] = list(_SESSION_SNAPSHOT_STATE_FIELDS)
        attribute_names.extend(
            field for field in relationship_fields if field not in attribute_names
        )
        await self._db.refresh(session, attribute_names=attribute_names)

    async def _run_stage_operation(
        self,
        *,
        session: ResearchSession,
        state_fields: tuple[str, ...] = (),
        operation: Callable[
            ["ResearchService", ResearchSession], Awaitable[_StageResultT]
        ],
    ) -> _StageResultT:
        if self._sessionmaker is None or session.id is None:
            return await operation(self, session)

        async with self._sessionmaker() as stage_db:
            stage_service = self._build_db_bound_service(stage_db)
            stage_session = await stage_service.get_session(session.id)
            self._copy_session_state_fields(
                source=session,
                target=stage_session,
                fields=state_fields,
            )
            result = await operation(stage_service, stage_session)
            relationship_fields = tuple(
                field
                for field in _SESSION_SNAPSHOT_RELATIONSHIP_FIELDS
                if field in stage_session.__dict__ or field in session.__dict__
            )
            await stage_db.commit()
            await self._refresh_session_snapshot(
                session=session,
                relationship_fields=relationship_fields,
            )
            return result

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        session = await self._session_repository.get_with_details(session_id)
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
        self._session_repository.add(session)
        await self._session_repository.flush()
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
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await persist_runtime_context_artifacts(
                artifact_store=stage_service._artifact_store,
                session=stage_session,
                runtime_context_snapshot=runtime_context_snapshot,
                task_graph_artifact_key=RUNTIME_TASK_GRAPH_ARTIFACT_KEY,
                live_board_artifact_key=RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
            )

        await self._run_stage_operation(session=session, operation=_write)

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
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await persist_runtime_execution_artifacts(
                artifact_store=stage_service._artifact_store,
                session=stage_session,
                plan_snapshot=plan_snapshot,
                task_graph_artifact_key=RUNTIME_TASK_GRAPH_ARTIFACT_KEY,
                live_board_artifact_key=RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
            )

        await self._run_stage_operation(session=session, operation=_write)

    async def _persist_runtime_activity_update(
        self,
        *,
        session: ResearchSession,
        update: ResearchRuntimeActivityUpdate,
    ) -> dict[str, object]:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> dict[str, object]:
            return await persist_runtime_activity_update(
                artifact_store=stage_service._artifact_store,
                session=stage_session,
                update=update,
                live_board_artifact_key=RUNTIME_LIVE_BOARD_ARTIFACT_KEY,
            )

        return await self._run_stage_operation(session=session, operation=_write)

    async def _persist_runtime_start(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> None:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await stage_service._event_store.append(
                session=stage_session,
                event_type="research.run.started",
                phase="runtime",
                payload={
                    "target_sources": [
                        item.value for item in plan_snapshot.target_sources
                    ],
                    "lc_agent_name": "deep-research",
                },
                trace_id=stage_session.trace_id,
            )
            await stage_service._persist_plan_progress_snapshot(
                session=stage_session,
                plan_snapshot=plan_snapshot,
                phase="runtime",
                current_step_index=1 if plan_snapshot.subtasks else None,
                completed_step_count=0,
            )

        await self._run_stage_operation(
            session=session,
            state_fields=("trace_id", "status", "runtime_phase", "started_at"),
            operation=_write,
        )

    async def _persist_runtime_results(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        runtime_result: ResearchRuntimeRunResult,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> None:
        source_bundle = runtime_result.source_bundle
        trace_links = build_trace_links(session=session, runtime_result=runtime_result)

        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await stage_service._sync_runtime_plan_progress_from_checkpoint(
                session=stage_session,
                plan_snapshot=plan_snapshot,
            )
            await stage_service._append_trace_events(
                session=stage_session,
                trace_links=trace_links,
            )
            await stage_service._artifact_store.upsert(
                session=stage_session,
                artifact_key="source_bundle",
                content_json={
                    "target_sources": [
                        item.value for item in source_bundle.target_sources
                    ],
                    "findings": list(source_bundle.findings),
                    "citations": [
                        citation.model_dump(mode="json")
                        for citation in source_bundle.citations
                    ],
                    "provider_counts": source_bundle.provider_counts,
                },
            )
            await stage_service._artifact_store.upsert(
                session=stage_session,
                artifact_key="interim_findings",
                content_json=list(source_bundle.findings),
            )
            await stage_service._artifact_store.upsert(
                session=stage_session,
                artifact_key="interim_summary",
                content_text=source_bundle.interim_summary,
            )
            await stage_service._artifact_store.upsert(
                session=stage_session,
                artifact_key="coverage_gaps",
                content_json=list(source_bundle.coverage_gaps),
            )
            await stage_service._persist_runtime_context_artifacts(
                session=stage_session,
                runtime_context_snapshot=runtime_context_snapshot,
            )
            if runtime_result.files_budget_snapshot is not None:
                await stage_service._artifact_store.upsert(
                    session=stage_session,
                    artifact_key="runtime_files_budget_snapshot",
                    content_json=runtime_result.files_budget_snapshot,
                )

        await self._run_stage_operation(session=session, operation=_write)

    async def _persist_finalizer_start(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
        coverage_gaps: list[str],
    ) -> None:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await stage_service._persist_plan_progress_snapshot(
                session=stage_session,
                plan_snapshot=plan_snapshot,
                phase="finalizer",
                current_step_index=None,
                completed_step_count=len(plan_snapshot.subtasks),
            )
            await stage_service._event_store.append(
                session=stage_session,
                event_type="research.finalizer.started",
                phase="finalizer",
                payload={
                    "coverage_gaps": list(coverage_gaps),
                    "lc_agent_name": "finalizer",
                },
                trace_id=stage_session.trace_id,
            )

        await self._run_stage_operation(
            session=session,
            state_fields=("status", "finalizer_phase"),
            operation=_write,
        )

    async def _persist_finalized_session(
        self,
        *,
        session: ResearchSession,
        final_result: ResearchFinalizerResult,
        metrics: dict[str, object],
    ) -> None:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await persist_final_report_artifacts(
                artifact_store=stage_service._artifact_store,
                session=stage_session,
                final_result=final_result,
            )
            await stage_service._persist_metrics_artifacts(
                session=stage_session,
                metrics=metrics,
            )
            await stage_service._event_store.append(
                session=stage_session,
                event_type="research.final.completed",
                phase="finalizer",
                payload={
                    "artifact_keys": [
                        "report_json",
                        "report_md",
                        "claim_map_json",
                        "coverage_matrix_json",
                        "conflicts_json",
                        "source_ledger_json",
                        "metrics_snapshot",
                        "gate_snapshot",
                    ],
                    "lc_agent_name": "finalizer",
                },
                trace_id=stage_session.trace_id,
            )

        await self._run_stage_operation(
            session=session,
            state_fields=("status", "finished_at"),
            operation=_write,
        )

    async def _persist_failed_session(
        self,
        *,
        session: ResearchSession,
        exc: Exception,
        phase: str,
        source_provider: str | None,
        fault: dict[str, object],
        metrics: dict[str, object],
        plan_snapshot: ResearchPlanSnapshot | None,
    ) -> None:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            if plan_snapshot is not None and not stage_session.status.is_terminal():
                await stage_service._persist_terminal_plan_progress_snapshot(
                    session=stage_session,
                    plan_snapshot=plan_snapshot,
                    phase=phase,
                    terminal_state="failed",
                )
            if not stage_session.status.is_terminal():
                stage_session.transition_to(ResearchSessionStatus.FAILED)
            await stage_service._event_store.append(
                session=stage_session,
                event_type="research.run.failed",
                phase=phase,
                payload={
                    "error": str(exc),
                    "fault": fault,
                    "lc_agent_name": "deep-research",
                    "source_provider": source_provider,
                },
                trace_id=stage_session.trace_id,
            )
            await stage_service._persist_metrics_artifacts(
                session=stage_session,
                metrics=metrics,
            )

        await self._run_stage_operation(
            session=session,
            state_fields=(
                "trace_id",
                "runtime_phase",
                "finalizer_phase",
                "error_message",
                "finished_at",
            ),
            operation=_write,
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
        max_rounds = get_settings().research_scoper_max_clarify_rounds
        normalized_question = str(session.question or "").strip()
        clarification_questions: list[str] = []
        clarification_answers: list[str] = []
        for event in session.events:
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
            "- 仅当研究对象或主比较维度仍未闭合时，才允许继续追问。\n"
            "- 时间范围、受众、输出形态等轻微模糊请采用保守假设，并写入 research_brief 或 budget_guidance。\n"
            f"- 当前澄清回答轮次：{current_round} / {max_rounds}。\n"
            f"- 达到 {max_rounds} 轮后必须直接生成研究计划，并在 research_brief 中保留尚未闭合维度的保守假设。"
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
        del cls
        max_rounds = get_settings().research_scoper_max_clarify_rounds
        submitted = ResearchService._clarification_submission_count(session)
        has_current_answer = bool(str(answer or "").strip())
        current_round = submitted + (1 if has_current_answer else 0)
        return current_round < max_rounds

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

        self._session_repository.add_task_outbox_entry(
            ResearchTaskOutbox(
                session_id=session.id,
                task_name=RESEARCH_SESSION_TASK_NAME,
                status=ResearchTaskOutboxStatus.PENDING,
                payload={},
            )
        )

    def trigger_outbox_dispatch(self) -> None:
        try:
            from app.worker.tasks.research_outbox_dispatcher import (
                dispatch_research_outbox,
            )

            dispatch_research_outbox.delay()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Failed to trigger research outbox dispatcher",
                extra={"error": str(exc)},
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
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await append_trace_events(
                event_store=stage_service._event_store,
                session=stage_session,
                trace_links=trace_links,
            )

        await self._run_stage_operation(session=session, operation=_write)

    async def _persist_metrics_artifacts(
        self,
        *,
        session: ResearchSession,
        metrics: dict[str, object],
    ) -> None:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> None:
            await persist_metrics_artifacts(
                artifact_store=stage_service._artifact_store,
                session=stage_session,
                metrics=metrics,
            )

        await self._run_stage_operation(session=session, operation=_write)

    async def _read_committed_session_status(
        self,
        *,
        session: ResearchSession,
    ) -> ResearchSessionStatus | None:
        if self._sessionmaker is not None and session.id is not None:
            async with self._sessionmaker() as stage_db:
                return await read_committed_session_status(
                    db=stage_db,
                    session=session,
                )
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
        snapshot = build_plan_progress_snapshot(
            plan_snapshot,
            current_step_index=current_step_index,
            completed_step_count=completed_step_count,
            active_step_status=active_step_status,
        )
        return await self._persist_plan_progress_snapshot_payload(
            session=session,
            phase=phase,
            snapshot=snapshot,
            event_message=event_message,
            emit_event=emit_event,
        )

    async def _persist_plan_progress_snapshot_payload(
        self,
        *,
        session: ResearchSession,
        phase: str,
        snapshot: dict[str, object],
        event_message: str | None = None,
        emit_event: bool = True,
    ) -> dict[str, object]:
        async def _write(
            stage_service: "ResearchService",
            stage_session: ResearchSession,
        ) -> dict[str, object]:
            normalized_message = normalize_plan_progress_message(event_message)
            existing_payload = stage_service._read_plan_progress_payload(stage_session)
            if (
                plan_progress_snapshot_equals(existing_payload, snapshot)
                and normalized_message is None
            ):
                return existing_payload if existing_payload is not None else snapshot
            await stage_service._artifact_store.upsert(
                session=stage_session,
                artifact_key=PLAN_PROGRESS_ARTIFACT_KEY,
                content_json=snapshot,
            )
            summary = normalized_message or build_plan_progress_summary(snapshot)
            if emit_event:
                await stage_service._event_store.append(
                    session=stage_session,
                    event_type=PLAN_PROGRESS_EVENT_TYPE,
                    phase=phase,
                    payload={
                        **snapshot,
                        "summary": summary,
                        "message": normalized_message,
                        "lc_agent_name": lc_agent_name_for_phase(phase),
                    },
                    trace_id=stage_session.trace_id,
                )
            return snapshot

        return await self._run_stage_operation(session=session, operation=_write)

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

    async def _sync_runtime_plan_progress_from_checkpoint(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> dict[str, object] | None:
        checkpoint_tuple = await CheckpointManager.get_state(session.thread_id)
        if checkpoint_tuple is None:
            return None
        checkpoint_payload = checkpoint_tuple.checkpoint
        if not isinstance(checkpoint_payload, dict):
            return None
        channel_values = checkpoint_payload.get("channel_values")
        if not isinstance(channel_values, dict):
            return None
        raw_todos = channel_values.get("todos")
        if not isinstance(raw_todos, list):
            return None
        if not any(
            isinstance(item, dict)
            and isinstance(item.get("content"), str)
            and "[plan-step-" in item.get("content", "")
            for item in raw_todos
        ):
            return None
        snapshot = build_plan_progress_snapshot_from_runtime_todos(
            plan_snapshot,
            todos=[item for item in raw_todos if isinstance(item, dict)],
        )
        return await self._persist_plan_progress_snapshot_payload(
            session=session,
            phase="runtime",
            snapshot=snapshot,
        )

    def _build_runtime_activity_callback(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ):
        async def _callback(update: ResearchRuntimeActivityUpdate) -> None:
            async def _write(
                stage_service: "ResearchService",
                stage_session: ResearchSession,
            ) -> dict[str, object]:
                live_board = await stage_service._persist_runtime_activity_update(
                    session=stage_session,
                    update=update,
                )
                await stage_service._sync_runtime_plan_progress_from_checkpoint(
                    session=stage_session,
                    plan_snapshot=plan_snapshot,
                )
                await stage_service._event_store.append(
                    session=stage_session,
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
                    trace_id=stage_session.trace_id,
                )
                return live_board

            await self._run_stage_operation(session=session, operation=_write)
            await self._commit_checkpoint()

        return _callback

    async def _commit_checkpoint(self) -> None:
        if self._sessionmaker is not None:
            return
        commit = getattr(self._db, "commit", None)
        if callable(commit):
            commit_result = commit()
            if inspect.isawaitable(commit_result):
                await commit_result


def build_research_service(
    *,
    db: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    runtime_runner: ResearchRuntimeRunner | None = None,
    session_repository: ResearchSessionRepository | None = None,
) -> ResearchService:
    settings = get_settings()
    try:
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=settings)
        alignment_structured_method = resolve_langchain_structured_output_method(
            snapshot.active_provider_config().provider
        )
    except RuntimeError:
        alignment_structured_method = "function_calling"
    judge = ResearchAlignmentJudge(
        model=create_chat_model_cached(
            settings=settings,
            use_previous_response_id=False,
        ),
        structured_method=alignment_structured_method,
    )
    return ResearchService(
        db=db,
        sessionmaker=sessionmaker,
        planner=ResearchPlanner(),
        runtime_runner=runtime_runner or UnconfiguredResearchRuntimeRunner(),
        finalizer=ResearchFinalizer(judge=judge),
        session_repository=session_repository,
        settings=settings,
    )
