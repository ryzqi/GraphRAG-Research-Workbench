"""研究 Celery 任务（ToolNode 研究链路）。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.research_graph import ResearchGraph
from app.core.checkpoint import CheckpointManager
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.evidence import Evidence, EvidenceSourceKind
from app.models.research_report import ResearchReport
from app.models.tool_extension import ExtensionStatus, ToolExtension
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
