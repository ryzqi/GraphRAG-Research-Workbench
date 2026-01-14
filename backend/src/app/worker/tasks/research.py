"""研究 Celery 任务（DeepAgents 研究链路）。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.deep_research_agent import DeepResearchAgent
from app.core.checkpoint import CheckpointManager
from app.db.session import get_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.mcp_client import MCPClient
from app.integrations.milvus_client import get_milvus_client
from app.integrations.redis_client import get_redis
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.evidence import Evidence, EvidenceSourceKind
from app.models.research_report import ResearchReport
from app.models.tool_extension import ExtensionStatus, ToolExtension
from app.services.retrieval_service import RetrievalService
from app.worker.celery_app import celery_app


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
    # 初始化检查点管理器
    await CheckpointManager.initialize()

    sessionmaker = get_sessionmaker()
    run_uuid = uuid.UUID(run_id)

    try:
        async with sessionmaker() as session:
            run = await session.get(AgentRun, run_uuid)
            if run is None:
                return

            # 检查是否已取消
            if run.status == AgentRunStatus.CANCELED:
                return

            run.started_at = datetime.now(timezone.utc)
            await session.commit()

            mcp: MCPClient | None = None
            graph_task: asyncio.Task | None = None
            try:
                # 初始化依赖
                milvus = get_milvus_client()
                embedding = EmbeddingClient()
                redis = get_redis()
                retrieval = RetrievalService(session, milvus, embedding, redis)
                mcp = MCPClient()

                extensions: list[ToolExtension] = []
                if allow_external:
                    stmt = select(ToolExtension).where(
                        ToolExtension.status == ExtensionStatus.ENABLED
                    )
                    ext_result = await session.execute(stmt)
                    extensions = ext_result.scalars().all()

                # 创建研究代理
                agent = DeepResearchAgent(
                    retrieval=retrieval,
                    mcp=mcp,
                    extensions=extensions,
                )

                # 使用 run_id 作为 thread_id 执行（支持取消：轮询 DB 状态并 cancel 协程）
                graph_task = asyncio.create_task(
                    agent.run(
                        question=question,
                        kb_ids=[uuid.UUID(kid) for kid in kb_ids],
                        allow_external=allow_external,
                        thread_id=run_id,
                    )
                )

                result = None
                while True:
                    done, _ = await asyncio.wait({graph_task}, timeout=1.0)
                    if done:
                        result = await graph_task
                        break

                    await session.refresh(run)
                    if run.status == AgentRunStatus.CANCELED:
                        graph_task.cancel()
                        try:
                            await graph_task
                        except asyncio.CancelledError:
                            pass
                        return
                    await session.commit()

                # 写入检索证据
                evidence_records = [
                    Evidence(
                        run_id=run_uuid,
                        source_kind=EvidenceSourceKind.KB,
                        kb_id=r.chunk.kb_id,
                        material_id=r.chunk.material_id,
                        chunk_id=r.chunk.id,
                        locator=r.chunk.locator,
                        excerpt=r.chunk.text[:500],
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
                }

            except Exception as exc:
                run.status = AgentRunStatus.FAILED
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)

                if graph_task is not None:
                    graph_task.cancel()

            finally:
                if mcp is not None:
                    await mcp.close()

            await session.commit()

    finally:
        await CheckpointManager.shutdown()
