"""研究报告导出器。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.evidence import Evidence
from app.models.research_report import ResearchReport


class ResearchExporter:
    """研究报告导出器。"""

    async def export(self, session: AsyncSession, run_id: uuid.UUID) -> str:
        """导出研究报告为 Markdown 格式。"""
        # 获取运行记录
        run = await session.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"运行记录不存在: {run_id}")

        # 获取研究报告
        stmt = select(ResearchReport).where(ResearchReport.run_id == run_id)
        result = await session.execute(stmt)
        report = result.scalar_one_or_none()

        # 获取证据
        stmt = select(Evidence).where(Evidence.run_id == run_id)
        result = await session.execute(stmt)
        evidence_list = list(result.scalars().all())

        # 构建导出内容
        lines: list[str] = []
        lines.append("# 深度研究报告导出")
        lines.append("")
        lines.append(f"**导出时间**: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"**运行 ID**: {run_id}")
        lines.append(f"**研究问题**: {run.question}")
        lines.append(f"**状态**: {run.status.value}")
        lines.append("")

        # 阶段摘要
        if run.stage_summaries:
            lines.append("## 阶段摘要")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(run.stage_summaries, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

        # 研究报告正文
        if report:
            lines.append("## 研究报告")
            lines.append("")
            lines.append(report.content_md)
            lines.append("")

            # 引用清单
            if report.citations:
                lines.append("## 引用清单")
                lines.append("")
                for citation in report.citations:
                    idx = citation.get("index", "?")
                    excerpt = citation.get("excerpt", "")[:100]
                    lines.append(f"- [{idx}] {excerpt}...")
                lines.append("")

        # 证据列表
        if evidence_list:
            lines.append("## 证据详情")
            lines.append("")
            for i, ev in enumerate(evidence_list, 1):
                lines.append(f"### 证据 {i}")
                lines.append(f"- **来源类型**: {ev.source_kind.value}")
                if ev.kb_id:
                    lines.append(f"- **知识库 ID**: {ev.kb_id}")
                if ev.material_id:
                    lines.append(f"- **资料 ID**: {ev.material_id}")
                lines.append(f"- **摘录**: {ev.excerpt[:200]}...")
                lines.append("")

        return "\n".join(lines)
