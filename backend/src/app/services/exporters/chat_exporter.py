"""对话导出器。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence


class ChatExporter:
    """对话导出器：导出问答+证据+阶段摘要。"""

    async def export(self, session: AsyncSession, run_id: uuid.UUID) -> str:
        """导出对话为 Markdown 格式。"""
        # 获取运行记录
        run = await session.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"运行记录不存在: {run_id}")

        # 获取会话及消息
        chat_session: ChatSession | None = None
        messages: list[ChatMessage] = []
        if run.session_id:
            chat_session = await session.get(ChatSession, run.session_id)
            if chat_session:
                stmt = select(ChatMessage).where(
                    ChatMessage.session_id == run.session_id
                ).order_by(ChatMessage.created_at)
                result = await session.execute(stmt)
                messages = list(result.scalars().all())

        # 获取证据
        stmt = select(Evidence).where(Evidence.run_id == run_id)
        result = await session.execute(stmt)
        evidence_list = list(result.scalars().all())

        # 构建导出内容
        lines: list[str] = []
        lines.append("# 对话导出")
        lines.append("")
        lines.append(f"**导出时间**: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"**运行 ID**: {run_id}")
        lines.append(f"**类型**: {run.run_type.value}")
        lines.append(f"**模式**: {run.mode.value}")
        lines.append(f"**状态**: {run.status.value}")
        lines.append("")

        # 会话信息
        if chat_session:
            lines.append("## 会话信息")
            lines.append("")
            lines.append(f"- **会话 ID**: {chat_session.id}")
            lines.append(f"- **类型**: {chat_session.session_type.value}")
            if chat_session.selected_kb_ids:
                kb_ids_str = ", ".join(str(kid) for kid in chat_session.selected_kb_ids)
                lines.append(f"- **选中知识库**: {kb_ids_str}")
            lines.append(f"- **允许外部调用**: {chat_session.allow_external}")
            lines.append("")

        # 对话历史
        if messages:
            lines.append("## 对话历史")
            lines.append("")
            for msg in messages:
                role_label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(
                    msg.role.value, msg.role.value
                )
                lines.append(f"### {role_label} ({msg.created_at.isoformat()})")
                lines.append("")
                lines.append(msg.content)
                lines.append("")

        # 阶段摘要
        if run.stage_summaries:
            lines.append("## 阶段摘要")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(run.stage_summaries, ensure_ascii=False, indent=2))
            lines.append("```")
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
                if ev.locator:
                    lines.append(f"- **定位**: {json.dumps(ev.locator, ensure_ascii=False)}")
                lines.append(f"- **摘录**: {ev.excerpt[:300]}...")
                lines.append("")

        return "\n".join(lines)
