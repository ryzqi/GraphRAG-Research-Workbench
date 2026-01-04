"""子代理协调工具。

支持 DeepAgents 子代理的创建和协调，实现多智能体协作模式。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field


class SubagentTask(BaseModel):
    """子代理任务。"""

    task_id: str = Field(..., description="任务 ID")
    task_type: Literal["retrieve", "analyze", "synthesize"] = Field(
        ..., description="任务类型"
    )
    instruction: str = Field(..., description="任务指令")
    input_data: dict = Field(default_factory=dict, description="输入数据")
    timeout_seconds: int = Field(default=60, ge=1, le=300, description="超时时间")


class SubagentCoordinateArgs(BaseModel):
    """子代理协调参数。"""

    tasks: list[SubagentTask] = Field(..., min_length=1, description="任务列表")
    execution_mode: Literal["parallel", "sequential", "dependency"] = Field(
        default="parallel", description="执行模式"
    )
    aggregation_strategy: Literal["merge", "vote", "best"] = Field(
        default="merge", description="结果聚合策略"
    )


@dataclass
class TaskResult:
    """任务执行结果。"""

    task_id: str
    status: Literal["succeeded", "failed", "timeout"]
    output: object = None
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class SubagentCoordinator:
    """子代理协调器。"""

    model: object = None
    tools: list = field(default_factory=list)

    async def execute_task(self, task: SubagentTask) -> TaskResult:
        """执行单个子代理任务。"""
        start_time = time.time()

        try:
            if self.model is None:
                output = await self._execute_mock(task)
            else:
                output = await self._execute_with_agent(task)

            duration_ms = int((time.time() - start_time) * 1000)
            return TaskResult(
                task_id=task.task_id,
                status="succeeded",
                output=output,
                duration_ms=duration_ms,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)
            return TaskResult(
                task_id=task.task_id,
                status="timeout",
                error=f"任务超时（{task.timeout_seconds}s）",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return TaskResult(
                task_id=task.task_id,
                status="failed",
                error=str(e),
                duration_ms=duration_ms,
            )

    async def _execute_mock(self, task: SubagentTask) -> dict:
        """模拟执行（无 DeepAgents 时）。"""
        await asyncio.sleep(0.1)
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "result": f"模拟执行结果: {task.instruction[:50]}...",
            "note": "请配置 DeepAgents 以启用真实子代理执行",
        }

    async def _execute_with_agent(self, task: SubagentTask) -> object:
        """使用 DeepAgents 执行任务。"""
        try:
            from deepagents import create_deep_agent
        except ImportError:
            return await self._execute_mock(task)

        agent = create_deep_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=f"你是一个专注于 {task.task_type} 任务的子代理。",
        )

        result = await asyncio.wait_for(
            agent.ainvoke({"input": task.instruction}),
            timeout=task.timeout_seconds,
        )

        if isinstance(result, dict) and "output" in result:
            return result["output"]
        return result

    async def execute_parallel(self, tasks: list[SubagentTask]) -> list[TaskResult]:
        """并行执行所有任务。"""
        coros = [self.execute_task(task) for task in tasks]
        return await asyncio.gather(*coros)

    async def execute_sequential(self, tasks: list[SubagentTask]) -> list[TaskResult]:
        """串行执行所有任务。"""
        results = []
        for task in tasks:
            result = await self.execute_task(task)
            results.append(result)
            if result.status != "succeeded":
                break
        return results

    async def execute_dependency(
        self, tasks: list[SubagentTask], dependencies: dict[str, list[str]]
    ) -> list[TaskResult]:
        """按依赖顺序执行任务。"""
        results: dict[str, TaskResult] = {}
        pending = {t.task_id: t for t in tasks}

        while pending:
            ready = []
            for task_id, task in pending.items():
                deps = dependencies.get(task_id, [])
                if all(d in results and results[d].status == "succeeded" for d in deps):
                    ready.append(task)

            if not ready:
                for task_id in pending:
                    results[task_id] = TaskResult(
                        task_id=task_id,
                        status="failed",
                        error="依赖任务未完成或失败",
                    )
                break

            batch_results = await asyncio.gather(
                *[self.execute_task(t) for t in ready]
            )
            for r in batch_results:
                results[r.task_id] = r
                pending.pop(r.task_id, None)

        return [results[t.task_id] for t in tasks if t.task_id in results]

    def aggregate_results(
        self, results: list[TaskResult], strategy: str
    ) -> object:
        """聚合任务结果。"""
        succeeded = [r for r in results if r.status == "succeeded"]

        if not succeeded:
            return None

        if strategy == "merge":
            merged = {}
            for r in succeeded:
                if isinstance(r.output, dict):
                    merged.update(r.output)
                else:
                    merged[r.task_id] = r.output
            return merged

        elif strategy == "vote":
            outputs = [r.output for r in succeeded]
            from collections import Counter
            counter = Counter(str(o) for o in outputs)
            most_common = counter.most_common(1)
            if most_common:
                winner_str = most_common[0][0]
                for o in outputs:
                    if str(o) == winner_str:
                        return o
            return outputs[0] if outputs else None

        elif strategy == "best":
            return succeeded[0].output if succeeded else None

        return None


def build_subagent_coordinate_tool(
    model: object = None,
    tools: list | None = None,
) -> BaseTool:
    """构建子代理协调工具。"""
    coordinator = SubagentCoordinator(model=model, tools=tools or [])

    async def _coordinate(
        tasks: list[dict],
        execution_mode: str = "parallel",
        aggregation_strategy: str = "merge",
    ) -> str:
        parsed_tasks = [SubagentTask(**t) for t in tasks]
        start_time = time.time()

        if execution_mode == "parallel":
            results = await coordinator.execute_parallel(parsed_tasks)
        elif execution_mode == "sequential":
            results = await coordinator.execute_sequential(parsed_tasks)
        else:
            deps = {t.task_id: t.input_data.get("dependencies", []) for t in parsed_tasks}
            results = await coordinator.execute_dependency(parsed_tasks, deps)

        total_time_ms = int((time.time() - start_time) * 1000)
        succeeded = sum(1 for r in results if r.status == "succeeded")
        failed = sum(1 for r in results if r.status != "succeeded")

        aggregated = coordinator.aggregate_results(results, aggregation_strategy)

        output = {
            "execution_summary": {
                "total_tasks": len(parsed_tasks),
                "succeeded": succeeded,
                "failed": failed,
                "execution_time_ms": total_time_ms,
            },
            "task_results": [r.to_dict() for r in results],
            "aggregated_result": aggregated,
            "stage_summary": {
                "mode": execution_mode,
                "strategy": aggregation_strategy,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        return json.dumps(output, ensure_ascii=False)

    return StructuredTool.from_function(
        name="subagent_coordinate",
        description="协调多个子代理执行任务，支持并行/串行/依赖执行模式和结果聚合。",
        args_schema=SubagentCoordinateArgs,
        coroutine=_coordinate,
    )
