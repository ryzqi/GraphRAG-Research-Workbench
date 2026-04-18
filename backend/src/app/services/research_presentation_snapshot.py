"""Research 页面展示快照构造。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import ResearchArtifactRead, ResearchEventEnvelope

_STEP_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("clarify", "澄清问题"),
    ("plan", "研究计划"),
    ("run", "执行研究"),
    ("report", "输出报告"),
)


def build_research_presentation_snapshot(
    *,
    session: ResearchSession,
    events: Sequence[ResearchEventEnvelope],
    artifacts: Sequence[ResearchArtifactRead],
) -> dict[str, Any]:
    artifact_by_key = {item.artifact_key: item for item in artifacts}
    surface = _resolve_surface(session.status)
    clarification_payload = _read_artifact_object(
        artifact_by_key, "clarification_request"
    )
    plan_payload = _read_artifact_object(artifact_by_key, "plan_snapshot")
    plan_progress_payload = _read_artifact_object(
        artifact_by_key, "plan_progress_snapshot"
    )
    live_board_payload = _read_artifact_object(
        artifact_by_key, "runtime_live_board_json"
    )
    report_payload = _read_artifact_object(artifact_by_key, "report_json")
    metrics_payload = _read_artifact_object(artifact_by_key, "metrics_snapshot")
    gate_payload = _read_artifact_object(artifact_by_key, "gate_snapshot")
    report_markdown = _read_artifact_text(artifact_by_key, "report_md")

    hero_subtitle = _build_hero_subtitle(
        status=session.status,
        clarification_payload=clarification_payload,
        plan_payload=plan_payload,
        report_payload=report_payload,
    )

    return {
        "surface": surface,
        "hero": {
            "eyebrow": "Deep Research",
            "title": str(session.question or "").strip() or "未命名研究任务",
            "subtitle": hero_subtitle,
        },
        "rail": {
            "steps": _build_rail_steps(status=session.status),
        },
        "clarification": (
            _build_clarification_section(
                session=session,
                clarification_payload=clarification_payload,
            )
            if surface == "clarifying"
            else None
        ),
        "plan": (
            _build_plan_section(plan_payload=plan_payload)
            if surface == "planning"
            else None
        ),
        "live": (
            _build_live_section(
                status=session.status,
                events=events,
                plan_payload=plan_payload,
                plan_progress_payload=plan_progress_payload,
                live_board_payload=live_board_payload,
                metrics_payload=metrics_payload,
            )
            if surface == "live"
            else None
        ),
        "report": (
            _build_report_section(
                report_markdown=report_markdown,
                report_payload=report_payload,
                metrics_payload=metrics_payload,
                gate_payload=gate_payload,
            )
            if surface == "final"
            else None
        ),
    }


def _resolve_surface(status: ResearchSessionStatus) -> str:
    if status == ResearchSessionStatus.CLARIFYING:
        return "clarifying"
    if status in {
        ResearchSessionStatus.QUEUED,
        ResearchSessionStatus.RUNNING,
        ResearchSessionStatus.FINALIZING,
        ResearchSessionStatus.FAILED,
        ResearchSessionStatus.CANCELED,
        ResearchSessionStatus.TIMED_OUT,
    }:
        return "live"
    if status == ResearchSessionStatus.FINAL:
        return "final"
    return "planning"


def _read_artifact_object(
    artifact_by_key: dict[str, ResearchArtifactRead],
    artifact_key: str,
) -> dict[str, Any]:
    value = artifact_by_key.get(artifact_key)
    payload = value.content_json if value is not None else None
    return payload if isinstance(payload, dict) else {}


def _read_artifact_text(
    artifact_by_key: dict[str, ResearchArtifactRead],
    artifact_key: str,
) -> str | None:
    value = artifact_by_key.get(artifact_key)
    content = value.content_text if value is not None else None
    if not isinstance(content, str):
        return None
    normalized = content.strip()
    return normalized or None


def _read_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _build_hero_subtitle(
    *,
    status: ResearchSessionStatus,
    clarification_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> str:
    if status == ResearchSessionStatus.CLARIFYING:
        return str(
            clarification_payload.get("summary") or "请先补齐研究边界，再开始深度研究。"
        )
    if status == ResearchSessionStatus.PLAN_READY:
        return str(
            plan_payload.get("summary") or "研究计划已生成，可继续调整后开始执行。"
        )
    if status == ResearchSessionStatus.QUEUED:
        return "研究任务已进入执行队列，正在等待资源调度。"
    if status == ResearchSessionStatus.RUNNING:
        return "正在整合研究线索、证据与中间发现。"
    if status == ResearchSessionStatus.FINALIZING:
        return "正在收口证据并生成最终报告。"
    if status == ResearchSessionStatus.FINAL:
        return str(
            report_payload.get("summary") or "研究报告已生成，可直接阅读与导出。"
        )
    if status == ResearchSessionStatus.FAILED:
        return "研究执行失败，请检查错误后重新发起。"
    if status == ResearchSessionStatus.CANCELED:
        return "当前研究已停止，可重新发起新的研究任务。"
    if status == ResearchSessionStatus.TIMED_OUT:
        return "当前研究执行超时，可调整范围后重试。"
    return "正在生成研究计划。"


def _build_rail_steps(status: ResearchSessionStatus) -> list[dict[str, str]]:
    states = {
        "clarify": "pending",
        "plan": "pending",
        "run": "pending",
        "report": "pending",
    }

    if status == ResearchSessionStatus.CLARIFYING:
        states["clarify"] = "current"
    elif status in {
        ResearchSessionStatus.CREATED,
        ResearchSessionStatus.PLANNING,
        ResearchSessionStatus.PLAN_READY,
    }:
        states["clarify"] = "complete"
        states["plan"] = "current"
    elif status in {
        ResearchSessionStatus.QUEUED,
        ResearchSessionStatus.RUNNING,
        ResearchSessionStatus.FAILED,
        ResearchSessionStatus.CANCELED,
        ResearchSessionStatus.TIMED_OUT,
    }:
        states["clarify"] = "complete"
        states["plan"] = "complete"
        states["run"] = "current"
    elif status == ResearchSessionStatus.FINALIZING:
        states["clarify"] = "complete"
        states["plan"] = "complete"
        states["run"] = "complete"
        states["report"] = "current"
    elif status == ResearchSessionStatus.FINAL:
        states["clarify"] = "complete"
        states["plan"] = "complete"
        states["run"] = "complete"
        states["report"] = "current"

    return [
        {"key": key, "label": label, "state": states[key]}
        for key, label in _STEP_DEFINITIONS
    ]


def _build_clarification_section(
    *,
    session: ResearchSession,
    clarification_payload: dict[str, Any],
) -> dict[str, Any]:
    questions = clarification_payload.get("questions")
    question_cards = []
    if isinstance(questions, list):
        for item in questions:
            if not isinstance(item, dict):
                continue
            title = str(item.get("question") or "").strip()
            description = str(item.get("why_it_matters") or "").strip()
            question_id = str(item.get("id") or "").strip()
            if not title or not question_id:
                continue
            question_cards.append(
                {
                    "id": question_id,
                    "title": title,
                    "description": description,
                }
            )

    return {
        "summary": str(clarification_payload.get("summary") or "").strip(),
        "question_cards": question_cards,
        "known_context": f"当前已收到的研究问题是：{str(session.question or '').strip()}",
        "input_placeholder": "回复以上问题以优化研究路径…",
        "submit_label": "提交补充信息",
    }


def _build_plan_section(*, plan_payload: dict[str, Any]) -> dict[str, Any]:
    raw_steps = plan_payload.get("subtasks")
    steps: list[dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            target_sources = item.get("target_sources")
            if not title:
                continue
            steps.append(
                {
                    "index": index,
                    "title": title,
                    "description": description,
                    "target_sources": target_sources
                    if isinstance(target_sources, list)
                    else [],
                }
            )

    return {
        "research_brief": str(plan_payload.get("research_brief") or "").strip(),
        "summary": str(plan_payload.get("summary") or "").strip(),
        "steps": steps,
        "target_sources": plan_payload.get("target_sources")
        if isinstance(plan_payload.get("target_sources"), list)
        else [],
        "secondary_action": {
            "label": "更新计划",
        },
        "primary_action": {
            "label": "开始研究",
        },
    }


def _build_live_section(
    *,
    status: ResearchSessionStatus,
    events: Sequence[ResearchEventEnvelope],
    plan_payload: dict[str, Any],
    plan_progress_payload: dict[str, Any],
    live_board_payload: dict[str, Any],
    metrics_payload: dict[str, Any],
) -> dict[str, Any]:
    plan_steps = _build_live_plan_steps(
        status=status,
        plan_payload=plan_payload,
        plan_progress_payload=plan_progress_payload,
    )
    progress = _build_live_progress(status=status, plan_steps=plan_steps)
    activity = _build_live_activity(events=events, status=status)
    quality_payload = metrics_payload.get("quality")
    citation_count = (
        quality_payload.get("citation_count")
        if isinstance(quality_payload, dict)
        else None
    )

    return {
        "progress": progress,
        "plan_steps": plan_steps,
        "activity": activity,
        "coverage_label": (
            f"已汇总 {int(citation_count)} 条引用"
            if isinstance(citation_count, (int, float))
            else "正在收集研究证据"
        ),
        "current_agent_label": str(
            live_board_payload.get("current_agent_label") or ""
        ).strip()
        or None,
        "current_task_label": str(
            live_board_payload.get("current_task_label") or ""
        ).strip()
        or None,
        "current_task_kind": str(
            live_board_payload.get("current_task_kind") or ""
        ).strip()
        or None,
        "parallel_tasks": _read_live_board_task_items(
            live_board_payload.get("parallel_tasks")
        ),
    }


def _normalize_plan_step_state(value: object) -> str:
    if value in {"pending", "current", "complete", "failed", "canceled"}:
        return str(value)
    return "pending"


def _build_live_plan_steps(
    *,
    status: ResearchSessionStatus,
    plan_payload: dict[str, Any],
    plan_progress_payload: dict[str, Any],
) -> list[dict[str, str]]:
    progress_steps = plan_progress_payload.get("steps")
    normalized_steps: list[dict[str, str]] = []
    if isinstance(progress_steps, list):
        for index, item in enumerate(progress_steps, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("title") or "").strip()
            if not label:
                continue
            normalized_steps.append(
                {
                    "key": f"plan-step-{index}",
                    "label": label,
                    "state": _normalize_plan_step_state(item.get("status")),
                }
            )
    if normalized_steps:
        return normalized_steps

    raw_steps = plan_payload.get("subtasks")
    if isinstance(raw_steps, list):
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("title") or "").strip()
            if not label:
                continue
            state = "pending"
            if status in {ResearchSessionStatus.FINALIZING, ResearchSessionStatus.FINAL}:
                state = "complete"
            elif status == ResearchSessionStatus.CANCELED:
                state = "canceled" if index == 1 else "pending"
            elif status in {ResearchSessionStatus.FAILED, ResearchSessionStatus.TIMED_OUT}:
                state = "failed" if index == 1 else "pending"
            elif status in {ResearchSessionStatus.QUEUED, ResearchSessionStatus.RUNNING}:
                state = "current" if index == 1 else "pending"
            normalized_steps.append(
                {"key": f"plan-step-{index}", "label": label, "state": state}
            )
        if normalized_steps:
            return normalized_steps

    generic_steps = [
        ("plan-step-1", "进入执行队列"),
        ("plan-step-2", "执行研究"),
        ("plan-step-3", "生成报告"),
    ]
    states = {
        "plan-step-1": "pending",
        "plan-step-2": "pending",
        "plan-step-3": "pending",
    }
    if status == ResearchSessionStatus.QUEUED:
        states["plan-step-1"] = "current"
    elif status == ResearchSessionStatus.RUNNING:
        states["plan-step-1"] = "complete"
        states["plan-step-2"] = "current"
    elif status in {ResearchSessionStatus.FINALIZING, ResearchSessionStatus.FINAL}:
        states["plan-step-1"] = "complete"
        states["plan-step-2"] = "complete"
        states["plan-step-3"] = "current"
    elif status == ResearchSessionStatus.CANCELED:
        states["plan-step-1"] = "canceled"
    elif status in {ResearchSessionStatus.FAILED, ResearchSessionStatus.TIMED_OUT}:
        states["plan-step-1"] = "failed"
    return [
        {"key": key, "label": label, "state": states[key]}
        for key, label in generic_steps
    ]


def _build_live_progress(
    *,
    status: ResearchSessionStatus,
    plan_steps: Sequence[dict[str, str]],
) -> dict[str, Any]:
    total_steps = len(plan_steps)
    completed_step_count = sum(
        1 for item in plan_steps if item.get("state") == "complete"
    )
    current_step = next(
        (
            item
            for item in plan_steps
            if item.get("state") in {"current", "failed", "canceled"}
        ),
        None,
    )
    current_stage_label = (
        str(current_step.get("label") or "").strip()
        if isinstance(current_step, dict)
        else ""
    )
    progress_percent = (
        int(round((completed_step_count / total_steps) * 100))
        if total_steps > 0
        else 0
    )
    if status == ResearchSessionStatus.QUEUED:
        return {
            "label": "研究准备中",
            "percent": progress_percent,
            "current_stage_label": current_stage_label or "进入执行队列",
        }
    if status == ResearchSessionStatus.RUNNING:
        return {
            "label": "研究执行中",
            "percent": progress_percent,
            "current_stage_label": current_stage_label or "执行研究",
        }
    if status == ResearchSessionStatus.FINALIZING:
        return {
            "label": "报告生成中",
            "percent": 88,
            "current_stage_label": "生成报告",
        }
    if status == ResearchSessionStatus.FAILED:
        return {
            "label": "研究失败",
            "percent": progress_percent,
            "current_stage_label": current_stage_label or "研究失败",
        }
    if status == ResearchSessionStatus.CANCELED:
        return {
            "label": "研究已停止",
            "percent": progress_percent,
            "current_stage_label": current_stage_label or "研究已停止",
        }
    if status == ResearchSessionStatus.TIMED_OUT:
        return {
            "label": "研究超时",
            "percent": progress_percent,
            "current_stage_label": current_stage_label or "研究超时",
        }
    return {
        "label": "执行研究",
        "percent": progress_percent,
        "current_stage_label": current_stage_label or "执行研究",
    }


def _build_live_activity(
    *,
    events: Sequence[ResearchEventEnvelope],
    status: ResearchSessionStatus,
) -> list[dict[str, Any]]:
    activity = []
    for event in sorted(events, key=lambda item: item.sequence, reverse=True)[:4]:
        activity.append(
            {
                "id": event.event_id,
                "event_type": event.event_type,
                "title": _build_activity_title(event),
                "body": _build_activity_body(event),
                "phase": event.phase,
            }
        )

    if activity:
        return activity

    return [
        {
            "id": "fallback-status",
            "event_type": f"status.{status.value}",
            "title": _build_status_activity_title(status),
            "body": "当前暂无更多研究事件，界面会在新事件到达后自动更新。",
            "phase": "runtime",
        }
    ]


def _build_activity_title(event: ResearchEventEnvelope) -> str:
    summary = event.payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if event.event_type == "research.trace.recorded":
        source_provider = event.payload.get("source_provider")
        if isinstance(source_provider, str) and source_provider.strip():
            return f"记录来源轨迹：{source_provider.strip()}"
        lc_agent_name = event.payload.get("lc_agent_name")
        if isinstance(lc_agent_name, str) and lc_agent_name.strip():
            return f"记录代理轨迹：{lc_agent_name.strip()}"
        return "记录研究轨迹"
    if event.event_type == "research.runtime.activity":
        title = event.payload.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return "记录运行时任务活动"
    mapping = {
        "research.run.started": "研究已启动",
        "research.run.queued": "研究已进入队列",
        "research.finalizer.started": "开始生成报告",
        "research.run.failed": "研究执行失败",
        "research.run.stopped": "研究已停止",
        "research.run.timed_out": "研究执行超时",
        "research.final.completed": "最终报告已生成",
    }
    return mapping.get(event.event_type, event.event_type)


def _build_activity_body(event: ResearchEventEnvelope) -> str:
    finding = event.payload.get("finding")
    if isinstance(finding, str) and finding.strip():
        return finding.strip()
    if event.event_type == "research.run.started":
        return "深度研究运行时已启动，开始执行证据收集与分析。"
    if event.event_type == "research.run.queued":
        return "任务已进入执行队列，正在等待运行资源。"
    if event.event_type == "research.finalizer.started":
        return "证据收集已接近完成，正在生成最终报告。"
    if event.event_type == "research.trace.recorded":
        source_provider = event.payload.get("source_provider")
        lc_agent_name = event.payload.get("lc_agent_name")
        tokens = [
            str(source_provider).strip()
            for source_provider in [source_provider]
            if isinstance(source_provider, str) and source_provider.strip()
        ]
        if isinstance(lc_agent_name, str) and lc_agent_name.strip():
            tokens.append(lc_agent_name.strip())
        if tokens:
            return f"最近活跃链路：{' / '.join(tokens)}"
        return "记录到新的研究链路轨迹。"
    if event.event_type == "research.runtime.activity":
        message = event.payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        current_task_label = event.payload.get("current_task_label")
        if isinstance(current_task_label, str) and current_task_label.strip():
            return f"当前任务：{current_task_label.strip()}"
        return "运行时任务活动已更新。"
    error_message = event.payload.get("error")
    if isinstance(error_message, str) and error_message.strip():
        return error_message.strip()
    return "研究状态已更新。"


def _build_status_activity_title(status: ResearchSessionStatus) -> str:
    mapping = {
        ResearchSessionStatus.QUEUED: "等待执行资源",
        ResearchSessionStatus.RUNNING: "正在执行研究",
        ResearchSessionStatus.FINALIZING: "正在生成报告",
        ResearchSessionStatus.FAILED: "研究执行失败",
        ResearchSessionStatus.CANCELED: "研究已停止",
        ResearchSessionStatus.TIMED_OUT: "研究执行超时",
    }
    return mapping.get(status, "研究状态更新")


def _read_live_board_task_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not task_id or not title:
            continue
        items.append(
            {
                "task_id": task_id,
                "title": title,
                "task_kind": str(item.get("task_kind") or "").strip() or None,
                "status": str(item.get("status") or "").strip() or None,
                "agent_label": str(item.get("agent_label") or "").strip() or None,
                "parallel_group": str(item.get("parallel_group") or "").strip()
                or None,
            }
        )
    return items


def _build_report_section(
    *,
    report_markdown: str | None,
    report_payload: dict[str, Any],
    metrics_payload: dict[str, Any],
    gate_payload: dict[str, Any],
) -> dict[str, Any]:
    summary = report_payload.get("summary")
    return {
        "badge_label": "已生成研究报告",
        "markdown": report_markdown or "",
        "summary": str(summary or "").strip(),
        "outline": _build_report_outline(
            report_payload=report_payload,
            report_markdown=report_markdown,
        ),
        "metric_cards": _build_report_metric_cards(
            metrics_payload=metrics_payload,
            gate_payload=gate_payload,
            report_payload=report_payload,
        ),
    }


def _build_report_outline(
    *, report_payload: dict[str, Any], report_markdown: str | None
) -> list[dict[str, Any]]:
    sections_payload = report_payload.get("sections")
    if isinstance(sections_payload, list):
        outline_from_sections: list[dict[str, Any]] = []
        for index, item in enumerate(sections_payload, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            section_id = str(item.get("id") or "").strip() or f"section-{index}"
            level = _read_int(item.get("level")) or 2
            outline_from_sections.append(
                {
                    "id": section_id,
                    "title": title,
                    "level": level,
                }
            )
        if outline_from_sections:
            return outline_from_sections

    if not report_markdown:
        return []
    outline = []
    index = 0
    for raw_line in report_markdown.splitlines():
        line = raw_line.strip()
        if not line.startswith("## "):
            continue
        title = line[3:].strip()
        if not title:
            continue
        index += 1
        outline.append(
            {
                "id": f"section-{index}",
                "title": title,
                "level": 2,
            }
        )
    return outline


def _build_report_metric_cards(
    *,
    metrics_payload: dict[str, Any],
    gate_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> list[dict[str, str]]:
    quality_payload = metrics_payload.get("quality")
    cost_payload = metrics_payload.get("cost")
    coverage_payload = metrics_payload.get("coverage")
    citation_count_raw = (
        quality_payload.get("citation_count") if isinstance(quality_payload, dict) else None
    )
    finding_count_raw = (
        quality_payload.get("finding_count") if isinstance(quality_payload, dict) else None
    )
    findings_payload = report_payload.get("findings")
    citation_count = (
        citation_count_value if (citation_count_value := _read_int(citation_count_raw)) is not None else 0
    )
    finding_count = (
        finding_count_value
        if (finding_count_value := _read_int(finding_count_raw)) is not None
        else (
            len(findings_payload) if isinstance(findings_payload, list) else 0
        )
    )
    gate_pass = gate_payload.get("pass")
    if not isinstance(gate_pass, bool) and isinstance(coverage_payload, dict):
        gate_pass = coverage_payload.get("pass")
    metric_cards = [
        {"label": "引用数", "value": str(citation_count)},
        {"label": "关键发现", "value": str(finding_count)},
        {"label": "覆盖状态", "value": "通过" if gate_pass else "待补证"},
    ]
    session_cost = (
        cost_payload.get("session_cost_usd") if isinstance(cost_payload, dict) else None
    )
    if isinstance(session_cost, (int, float)):
        metric_cards.append(
            {"label": "会话成本", "value": f"${float(session_cost):.2f}"}
        )
    return metric_cards
