"""评测结果导出器。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_run import EvaluationRun


class EvaluationExporter:
    """评测结果导出器。"""

    async def export(self, session: AsyncSession, run_id: uuid.UUID) -> str:
        """导出评测结果为 Markdown 格式。"""
        eval_run = await session.get(EvaluationRun, run_id)
        if eval_run is None:
            raise ValueError(f"评测记录不存在: {run_id}")

        lines: list[str] = []
        lines.append("# 对比评测结果导出")
        lines.append("")
        lines.append(f"**导出时间**: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"**评测 ID**: {run_id}")
        lines.append(f"**状态**: {eval_run.status.value}")
        lines.append("")

        # 配置信息
        lines.append("## 评测配置")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(eval_run.config, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

        # 汇总指标
        if eval_run.summary:
            lines.append("## 汇总指标")
            lines.append("")
            summary = eval_run.summary
            if "single_agent" in summary:
                lines.append("### 单智能体")
                lines.append(f"- 平均耗时: {summary['single_agent'].get('avg_latency', 'N/A')}ms")
                lines.append(f"- 平均得分: {summary['single_agent'].get('avg_score', 'N/A')}")
            if "multi_agent" in summary:
                lines.append("### 多智能体")
                lines.append(f"- 平均耗时: {summary['multi_agent'].get('avg_latency', 'N/A')}ms")
                lines.append(f"- 平均得分: {summary['multi_agent'].get('avg_score', 'N/A')}")
            lines.append("")

        # 题目明细
        if eval_run.summary and "case_results" in eval_run.summary:
            lines.append("## 题目明细")
            lines.append("")
            for i, case in enumerate(eval_run.summary["case_results"], 1):
                lines.append(f"### 题目 {i}: {case.get('question', '')[:50]}...")
                lines.append(f"- 单智能体得分: {case.get('single_score', 'N/A')}")
                lines.append(f"- 多智能体得分: {case.get('multi_score', 'N/A')}")
                lines.append("")

        # 原始数据集
        lines.append("## 原始数据集")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(eval_run.dataset, ensure_ascii=False, indent=2))
        lines.append("```")

        return "\n".join(lines)
