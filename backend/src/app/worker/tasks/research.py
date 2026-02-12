"""研究 Celery 任务（ToolNode 研究链路）。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.deep_research_agent import DeepResearchAgent
from app.agents.research_graph import ResearchGraph
from app.core.checkpoint import CheckpointManager
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.evidence import Evidence, EvidenceSourceKind
from app.models.research_session import (
    TERMINAL_RESEARCH_SESSION_STATUSES,
    ResearchSession,
    ResearchSessionStatus,
)
from app.models.research_report import ResearchReport
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.services.research_v2_service import ResearchArtifactStore, ResearchEventStore
from app.services.retrieval_service import RetrievalService
from app.services.streaming import StreamState, apply_updates_chunk
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources


@celery_app.task(name="app.worker.tasks.research.run_research")
def run_research(
    run_id: str,
    question: str,
    kb_ids: list[str],
    allow_external: bool,
    mode: str,
) -> None:
    """执行研究任务。"""
    asyncio.run(
        _run_research(
            run_id=run_id,
            question=question,
            kb_ids=kb_ids,
            allow_external=allow_external,
            mode=mode,
        )
    )


async def _run_research(
    *,
    run_id: str,
    question: str,
    kb_ids: list[str],
    allow_external: bool,
    mode: str,
) -> None:
    """异步执行研究任务（支持线程级记忆）。"""
    settings = None
    run_uuid = uuid.UUID(run_id)

    try:
        # 初始化检查点管理器
        await CheckpointManager.initialize()

        settings = get_settings()
        async with managed_task_resources(
            settings=settings,
            with_engine=True,
            with_http=True,
            with_redis=True,
            with_milvus=True,
        ) as resources:
            sessionmaker = resources.sessionmaker
            if sessionmaker is None:  # pragma: no cover - defensive
                return
            async with sessionmaker() as session:
                run = await session.get(AgentRun, run_uuid)
                if run is None:
                    return

                # 检查是否已取消
                if run.status == AgentRunStatus.CANCELED:
                    return

                run.started_at = datetime.now(timezone.utc)
                await session.commit()

                try:
                    # 初始化依赖（每任务创建）
                    http_client = resources.http_client
                    milvus = resources.milvus
                    embedding = EmbeddingClient(http_client=http_client)
                    redis = resources.redis
                    retrieval = RetrievalService(session, milvus, embedding, redis)

                    extensions: list[ToolExtension] = []
                    if allow_external:
                        stmt = select(ToolExtension).where(
                            ToolExtension.status == ExtensionStatus.ENABLED
                        )
                        ext_result = await session.execute(stmt)
                        extensions = ext_result.scalars().all()

                    graph = ResearchGraph()

                    compiled, state, config, retrieval_results = await graph.build_runtime(
                        question=question,
                        kb_ids=[uuid.UUID(kid) for kid in kb_ids],
                        retrieval=retrieval,
                        extensions=list(extensions),
                        allow_external=allow_external,
                        thread_id=run_id,
                        checkpointer=CheckpointManager.get_checkpointer(),
                        redis=redis,
                        http_client=http_client,
                    )

                    stream_state = StreamState(
                        messages=list(state.get("messages", []))
                        if isinstance(state.get("messages", []), list)
                        else [],
                        pending_tool_calls=[],
                        stage_summaries={},
                        metrics={},
                    )
                    last_stage: dict | None = None
                    last_metrics: dict | None = None
                    last_values: dict | None = None

                    stream = compiled.astream(state, config, stream_mode=["updates", "values"])
                    while True:
                        try:
                            mode, chunk = await asyncio.wait_for(
                                stream.__anext__(), timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            await session.refresh(run)
                            if run.status == AgentRunStatus.CANCELED:
                                return
                            continue
                        except StopAsyncIteration:
                            break

                        if mode == "updates" and isinstance(chunk, dict):
                            apply_updates_chunk(stream_state, chunk)
                            if (
                                stream_state.stage_summaries
                                and stream_state.stage_summaries != last_stage
                            ):
                                run.stage_summaries = stream_state.stage_summaries
                                last_stage = dict(stream_state.stage_summaries)
                                await session.commit()
                            if stream_state.metrics and stream_state.metrics != last_metrics:
                                run.metrics = stream_state.metrics
                                last_metrics = dict(stream_state.metrics)
                                await session.commit()
                        elif mode == "values" and isinstance(chunk, dict):
                            last_values = chunk

                    result_dict = last_values or {
                        "messages": stream_state.messages,
                        "stage_summaries": stream_state.stage_summaries,
                        "metrics": stream_state.metrics,
                    }
                    result = graph.build_output(result_dict, retrieval_results)

                    # 写入检索证据
                    evidence_records = [
                        Evidence(
                            run_id=run_uuid,
                            source_kind=EvidenceSourceKind.KB,
                            kb_id=r.chunk.kb_id,
                            material_id=r.chunk.material_id,
                            chunk_id=r.chunk.id,
                            locator=r.chunk.locator,
                            excerpt=r.chunk.content[:500],
                        )
                        for r in result.retrieval_results
                    ]
                    if evidence_records:
                        session.add_all(evidence_records)

                    # 保存研究报告
                    report = ResearchReport(
                        run_id=run_uuid,
                        content_md=result.report_md,
                        citations=result.citations,
                    )
                    session.add(report)

                    # 更新运行状态
                    run.status = AgentRunStatus.SUCCEEDED
                    run.finished_at = datetime.now(timezone.utc)
                    run.final_output = result.report_md[:1000]  # 截取摘要
                    run.stage_summaries = result.stage_summaries
                    run.metrics = {
                        "citation_count": len(result.citations),
                        "retrieval_count": len(result.retrieval_results),
                        **(result.metrics or {}),
                    }

                except Exception as exc:
                    run.status = AgentRunStatus.FAILED
                    run.finished_at = datetime.now(timezone.utc)
                    run.error_message = str(exc)

                await session.commit()

    finally:
        try:
            await CheckpointManager.shutdown()
        except Exception:  # pragma: no cover - best effort
            pass


@celery_app.task(name="app.worker.tasks.research.run_research_v2")
def run_research_v2(
    session_id: str,
    resume_from_event_id: str | None,
    idempotency_key: str | None,
    decision: str,
    instructions: str | None,
) -> None:
    """执行 research v2 任务。"""
    asyncio.run(
        _run_research_v2(
            session_id=session_id,
            resume_from_event_id=resume_from_event_id,
            idempotency_key=idempotency_key,
            decision=decision,
            instructions=instructions,
        )
    )


async def _run_research_v2(
    *,
    session_id: str,
    resume_from_event_id: str | None,
    idempotency_key: str | None,
    decision: str,
    instructions: str | None,
) -> None:
    """异步执行 v2 研究任务（DeepAgents 单入口）。"""
    settings = get_settings()
    session_uuid = uuid.UUID(session_id)

    try:
        await CheckpointManager.initialize()
        async with managed_task_resources(
            settings=settings,
            with_engine=True,
            with_http=True,
            with_redis=True,
            with_milvus=True,
        ) as resources:
            sessionmaker = resources.sessionmaker
            if sessionmaker is None:  # pragma: no cover - defensive
                return

            async with sessionmaker() as db:
                run_session = await db.get(ResearchSession, session_uuid)
                if run_session is None:
                    return
                if run_session.status in TERMINAL_RESEARCH_SESSION_STATUSES:
                    return

                event_store = ResearchEventStore(db)
                artifact_store = ResearchArtifactStore(db)

                run_session.status = ResearchSessionStatus.RUNNING
                if run_session.started_at is None:
                    run_session.started_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(run_session)
                await event_store.append(
                    session_obj=run_session,
                    event_type="session.running",
                    payload={
                        "resume_from_event_id": resume_from_event_id,
                        "idempotency_key": idempotency_key,
                        "decision": decision,
                        "has_instructions": bool(instructions),
                    },
                    idempotency_key=idempotency_key,
                )

                try:
                    http_client = resources.http_client
                    milvus = resources.milvus
                    redis = resources.redis
                    if (
                        http_client is None
                        or milvus is None
                        or redis is None
                    ):  # pragma: no cover - defensive
                        raise RuntimeError("研究任务资源初始化失败")

                    embedding = EmbeddingClient(http_client=http_client)
                    retrieval = RetrievalService(db, milvus, embedding, redis)

                    # v2 研究路径不再装配 MCP 扩展，保留空列表占位。
                    deep_agent = DeepResearchAgent(
                        retrieval=retrieval,
                        extensions=[],
                        redis=redis,
                        http_client=http_client,
                    )
                    output = await deep_agent.run(
                        question=run_session.question,
                        kb_ids=list(run_session.selected_kb_ids or []),
                        allow_external=run_session.allow_external,
                        thread_id=run_session.thread_id,
                        enable_subagents=run_session.mode.value == "multi_agent",
                    )

                    report_json = {
                        "report_md": output.report_md,
                        "citations": output.citations,
                        "stage_summaries": output.stage_summaries,
                    }
                    await artifact_store.upsert_text(
                        session_id=run_session.id,
                        key="report_md",
                        content=output.report_md,
                    )
                    await artifact_store.upsert_json(
                        session_id=run_session.id,
                        key="report_json",
                        content=report_json,
                    )
                    await event_store.append(
                        session_obj=run_session,
                        event_type="artifact.updated",
                        payload={"keys": ["report_md", "report_json"]},
                    )

                    run_session.status = ResearchSessionStatus.FINAL
                    run_session.finished_at = datetime.now(timezone.utc)
                    run_session.final_output = output.report_md[:1000]
                    run_session.stage_summaries = output.stage_summaries
                    run_session.metrics = {
                        "citation_count": len(output.citations),
                        "retrieval_count": len(output.retrieval_results),
                    }
                    run_session.error_message = None
                    await db.commit()
                    await db.refresh(run_session)
                    await event_store.append(
                        session_obj=run_session,
                        event_type="session.final",
                        payload={
                            "status": run_session.status.value,
                            "metrics": run_session.metrics or {},
                        },
                    )
                except Exception as exc:
                    await db.rollback()
                    run_session = await db.get(ResearchSession, session_uuid)
                    if run_session is None:
                        return
                    run_session.status = ResearchSessionStatus.FAILED
                    run_session.finished_at = datetime.now(timezone.utc)
                    run_session.error_message = str(exc)
                    await db.commit()
                    await db.refresh(run_session)
                    await event_store.append(
                        session_obj=run_session,
                        event_type="session.failed",
                        payload={"error": str(exc)},
                        idempotency_key=idempotency_key,
                    )
    finally:
        try:
            await CheckpointManager.shutdown()
        except Exception:  # pragma: no cover - best effort
            pass
