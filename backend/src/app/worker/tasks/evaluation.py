"""评测 Celery 任务。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode
from app.models.evaluation_run import EvaluationRun, EvaluationStatus
from app.services.retrieval_service import RetrievalService
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources


@celery_app.task(name="app.worker.tasks.evaluation.run_evaluation")
def run_evaluation(eval_run_id: str) -> None:
    """执行评测任务。"""
    asyncio.run(_run_evaluation(eval_run_id=eval_run_id))


async def _run_evaluation(*, eval_run_id: str) -> None:
    """异步执行评测任务。"""
    settings = get_settings()
    run_uuid = uuid.UUID(eval_run_id)
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
            eval_run = await session.get(EvaluationRun, run_uuid)
            if eval_run is None:
                return

            if eval_run.status == EvaluationStatus.CANCELED:
                return

            eval_run.status = EvaluationStatus.RUNNING
            eval_run.started_at = datetime.now(timezone.utc)
            await session.commit()

            try:
                # 初始化依赖（每任务创建）
                http_client = resources.http_client
                llm = LLMClient(http_client=http_client)
                milvus = resources.milvus
                embedding = EmbeddingClient(http_client=http_client)
                redis = resources.redis
                retrieval = RetrievalService(session, milvus, embedding, redis)

                # 解析配置
                config = eval_run.config
                kb_ids = [uuid.UUID(kid) for kid in config.get("selected_kb_ids", [])]
                allow_external = config.get("allow_external", False)

                # 解析问题集
                dataset = eval_run.dataset
                questions = dataset.get("questions", [])

                eval_run.summary = {
                    "total_questions": len(questions),
                    "completed_questions": 0,
                }
                await session.commit()

                case_results: list[dict] = []
                single_metrics: list[dict] = []
                multi_metrics: list[dict] = []

                for q in questions:
                    # 取消检查点（长循环内定期探测）
                    await session.refresh(eval_run)
                    if eval_run.status == EvaluationStatus.CANCELED:
                        return

                    question_id = q.get("id", str(uuid.uuid4()))
                    question_text = q.get("question", "")
                    reference = q.get("reference_answer", "")

                    # 单智能体运行
                    single_result = await _run_single_agent(
                        session=session,
                        llm=llm,
                        retrieval=retrieval,
                        question=question_text,
                        kb_ids=kb_ids,
                        allow_external=allow_external,
                    )

                    # 多智能体运行
                    multi_result = await _run_multi_agent(
                        session=session,
                        llm=llm,
                        retrieval=retrieval,
                        question=question_text,
                        kb_ids=kb_ids,
                        allow_external=allow_external,
                    )

                    # 评分
                    single_score = await _score_answer(
                        llm, question_text, single_result["answer"], reference
                    )
                    multi_score = await _score_answer(
                        llm, question_text, multi_result["answer"], reference
                    )

                    case_results.append({
                        "question_id": question_id,
                        "question": question_text,
                        "single_agent_run_id": str(single_result["run_id"]),
                        "multi_agent_run_id": str(multi_result["run_id"]),
                        "single_agent_answer": single_result["answer"][:500],
                        "multi_agent_answer": multi_result["answer"][:500],
                        "single_score": single_score,
                        "multi_score": multi_score,
                        "reference_answer": reference[:200],
                    })

                    single_metrics.append({
                        "score": single_score,
                        "latency_ms": single_result["latency_ms"],
                    })
                    multi_metrics.append({
                        "score": multi_score,
                        "latency_ms": multi_result["latency_ms"],
                    })

                    completed = len(case_results)
                    eval_run.summary = {
                        "total_questions": len(questions),
                        "completed_questions": completed,
                        "single_agent": {
                            "avg_score": _avg([m["score"] for m in single_metrics]),
                            "avg_latency": _avg([m["latency_ms"] for m in single_metrics]),
                        },
                        "multi_agent": {
                            "avg_score": _avg([m["score"] for m in multi_metrics]),
                            "avg_latency": _avg([m["latency_ms"] for m in multi_metrics]),
                        },
                        "case_results": case_results,
                    }
                    await session.commit()

                # 计算汇总指标
                summary = {
                    "total_questions": len(questions),
                    "completed_questions": len(questions),
                    "single_agent": {
                        "avg_score": _avg([m["score"] for m in single_metrics]),
                        "avg_latency": _avg([m["latency_ms"] for m in single_metrics]),
                    },
                    "multi_agent": {
                        "avg_score": _avg([m["score"] for m in multi_metrics]),
                        "avg_latency": _avg([m["latency_ms"] for m in multi_metrics]),
                    },
                    "case_results": case_results,
                }

                eval_run.status = EvaluationStatus.SUCCEEDED
                eval_run.finished_at = datetime.now(timezone.utc)
                eval_run.summary = summary

            except Exception as exc:
                eval_run.status = EvaluationStatus.FAILED
                eval_run.finished_at = datetime.now(timezone.utc)
                eval_run.error_message = str(exc)

            await session.commit()


async def _run_single_agent(
    *,
    session,
    llm: LLMClient,
    retrieval: RetrievalService,
    question: str,
    kb_ids: list[uuid.UUID],
    allow_external: bool,
) -> dict:
    """单智能体运行。"""
    started_at = datetime.now(timezone.utc)

    # 创建运行记录
    run = AgentRun(
        run_type=AgentRunType.EVALUATION_CASE,
        question=question,
        selected_kb_ids=kb_ids,
        allow_external=allow_external,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
        started_at=started_at,
    )
    session.add(run)
    await session.flush()

    try:
        # 检索
        results = await retrieval.retrieve(query=question, kb_ids=kb_ids, top_k=5)
        context = "\n\n".join([f"[{i+1}] {r.context_text or r.chunk.content}" for i, r in enumerate(results)])

        # 生成答案
        messages = [
            LLMMessage(role="system", content=f"根据以下内容回答问题：\n{context}"),
            LLMMessage(role="user", content=question),
        ]
        answer = (await llm.chat_with_metrics(messages=messages)).content

        run.status = AgentRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        run.final_output = answer

    except Exception as e:
        run.status = AgentRunStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = str(e)
        answer = ""

    await session.commit()

    latency_ms = int((run.finished_at - started_at).total_seconds() * 1000)
    return {"run_id": run.id, "answer": answer, "latency_ms": latency_ms}


async def _run_multi_agent(
    *,
    session,
    llm: LLMClient,
    retrieval: RetrievalService,
    question: str,
    kb_ids: list[uuid.UUID],
    allow_external: bool,
) -> dict:
    """多智能体协作运行。"""
    started_at = datetime.now(timezone.utc)

    run = AgentRun(
        run_type=AgentRunType.EVALUATION_CASE,
        question=question,
        selected_kb_ids=kb_ids,
        allow_external=allow_external,
        mode=AgentMode.MULTI_AGENT,
        status=AgentRunStatus.RUNNING,
        started_at=started_at,
    )
    session.add(run)
    await session.flush()

    try:
        # 检索
        results = await retrieval.retrieve(query=question, kb_ids=kb_ids, top_k=8)
        context = "\n\n".join([f"[{i+1}] {r.context_text or r.chunk.content}" for i, r in enumerate(results)])

        # 阶段1：分析问题
        analysis_msg = [
            LLMMessage(role="system", content="你是问题分析专家，分析问题的关键点和所需信息。"),
            LLMMessage(role="user", content=f"分析问题：{question}"),
        ]
        analysis = (await llm.chat_with_metrics(messages=analysis_msg)).content

        # 阶段2：检索评估
        eval_msg = [
            LLMMessage(role="system", content="你是信息评估专家，评估检索内容的相关性和可靠性。"),
            LLMMessage(role="user", content=f"问题分析：{analysis}\n\n检索内容：{context}\n\n评估相关性。"),
        ]
        evaluation = (await llm.chat_with_metrics(messages=eval_msg)).content

        # 阶段3：综合回答
        synthesis_msg = [
            LLMMessage(
                role="system",
                content="你是综合回答专家，基于分析和评估生成准确、完整的答案。",
            ),
            LLMMessage(
                role="user",
                content=f"问题：{question}\n分析：{analysis}\n评估：{evaluation}\n内容：{context}\n\n生成答案。",
            ),
        ]
        answer = (await llm.chat_with_metrics(messages=synthesis_msg)).content

        run.status = AgentRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        run.final_output = answer
        run.stage_summaries = {
            "analysis": analysis[:200],
            "evaluation": evaluation[:200],
        }

    except Exception as e:
        run.status = AgentRunStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = str(e)
        answer = ""

    await session.commit()

    latency_ms = int((run.finished_at - started_at).total_seconds() * 1000)
    return {"run_id": run.id, "answer": answer, "latency_ms": latency_ms}


async def _score_answer(llm: LLMClient, question: str, answer: str, reference: str) -> float:
    """使用 LLM 评分。"""
    if not answer:
        return 0.0

    messages = [
        LLMMessage(
            role="system",
            content="你是评分专家。根据参考答案评估回答质量，返回 0-100 的分数（仅返回数字）。",
        ),
        LLMMessage(
            role="user",
            content=f"问题：{question}\n参考答案：{reference}\n待评估答案：{answer}\n\n分数：",
        ),
    ]
    try:
        result = (await llm.chat_with_metrics(messages=messages)).content
        score = float(result.strip().split()[0])
        return min(100.0, max(0.0, score))
    except (ValueError, IndexError):
        return 50.0


def _avg(values: list[float]) -> float:
    """计算平均值。"""
    return sum(values) / len(values) if values else 0.0
