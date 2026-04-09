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
    report_payload = _read_artifact_object(artifact_by_key, "report_json")
    metrics_payload = _read_artifact_object(artifact_by_key, "metrics_snapshot")
    gate_payload = _read_artifact_object(artifact_by_key, "gate_snapshot")
    source_ledger_payload = _read_artifact_array(artifact_by_key, "source_ledger_json")
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
                source_ledger_payload=source_ledger_payload,
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


def _read_artifact_array(
    artifact_by_key: dict[str, ResearchArtifactRead],
    artifact_key: str,
) -> list[dict[str, Any]]:
    value = artifact_by_key.get(artifact_key)
    payload = value.content_json if value is not None else None
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


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
    metrics_payload: dict[str, Any],
) -> dict[str, Any]:
    progress = _build_live_progress(status=status)
    activity = _build_live_activity(events=events, status=status)
    quality_payload = metrics_payload.get("quality")
    citation_count = (
        quality_payload.get("citation_count")
        if isinstance(quality_payload, dict)
        else None
    )

    return {
        "progress": progress,
        "pipeline_steps": _build_live_pipeline_steps(status=status),
        "activity": activity,
        "coverage_label": (
            f"已汇总 {int(citation_count)} 条引用"
            if isinstance(citation_count, (int, float))
            else "正在收集研究证据"
        ),
    }


def _build_live_pipeline_steps(
    *, status: ResearchSessionStatus
) -> list[dict[str, str]]:
    states = {
        "collect": "pending",
        "extract": "pending",
        "model": "pending",
        "report": "pending",
    }
    if status == ResearchSessionStatus.QUEUED:
        states["collect"] = "current"
    elif status in {
        ResearchSessionStatus.RUNNING,
        ResearchSessionStatus.FAILED,
        ResearchSessionStatus.CANCELED,
        ResearchSessionStatus.TIMED_OUT,
    }:
        states["collect"] = "complete"
        states["extract"] = "complete"
        states["model"] = "current"
    elif status in {ResearchSessionStatus.FINALIZING, ResearchSessionStatus.FINAL}:
        states["collect"] = "complete"
        states["extract"] = "complete"
        states["model"] = "complete"
        states["report"] = "current"

    return [
        {"key": "collect", "label": "数据收集", "state": states["collect"]},
        {"key": "extract", "label": "特征提取", "state": states["extract"]},
        {"key": "model", "label": "语义建模", "state": states["model"]},
        {"key": "report", "label": "结论生成", "state": states["report"]},
    ]


def _build_live_progress(*, status: ResearchSessionStatus) -> dict[str, Any]:
    if status == ResearchSessionStatus.QUEUED:
        return {
            "label": "研究准备中",
            "percent": 28,
            "current_stage_label": "进入执行队列",
        }
    if status == ResearchSessionStatus.RUNNING:
        return {
            "label": "研究执行中",
            "percent": 64,
            "current_stage_label": "执行研究",
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
            "percent": 100,
            "current_stage_label": "研究失败",
        }
    if status == ResearchSessionStatus.CANCELED:
        return {
            "label": "研究已停止",
            "percent": 100,
            "current_stage_label": "研究已停止",
        }
    if status == ResearchSessionStatus.TIMED_OUT:
        return {
            "label": "研究超时",
            "percent": 100,
            "current_stage_label": "研究超时",
        }
    return {
        "label": "执行研究",
        "percent": 60,
        "current_stage_label": "执行研究",
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
    if event.event_type == "research.trace.recorded":
        source_provider = event.payload.get("source_provider")
        if isinstance(source_provider, str) and source_provider.strip():
            return f"记录来源轨迹：{source_provider.strip()}"
        lc_agent_name = event.payload.get("lc_agent_name")
        if isinstance(lc_agent_name, str) and lc_agent_name.strip():
            return f"记录代理轨迹：{lc_agent_name.strip()}"
        return "记录研究轨迹"
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


def _build_report_section(
    *,
    report_markdown: str | None,
    report_payload: dict[str, Any],
    metrics_payload: dict[str, Any],
    gate_payload: dict[str, Any],
    source_ledger_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    findings = report_payload.get("findings")
    summary = report_payload.get("summary")
    return {
        "badge_label": "已生成研究报告",
        "markdown": report_markdown or "",
        "summary": str(summary or "").strip(),
        "lead": str(summary or "").strip(),
        "highlights": findings if isinstance(findings, list) else [],
        "outline": _build_report_outline(report_markdown),
        "metric_cards": _build_report_metric_cards(
            metrics_payload=metrics_payload,
            gate_payload=gate_payload,
            report_payload=report_payload,
        ),
        "chart": _build_report_chart(
            metrics_payload=metrics_payload,
            report_payload=report_payload,
        ),
        "spotlight_cards": _build_report_spotlight_cards(
            source_ledger_payload=source_ledger_payload
        ),
        "outlook_cards": _build_report_outlook_cards(report_payload=report_payload),
        "references": _build_report_references(
            report_payload=report_payload,
            source_ledger_payload=source_ledger_payload,
        ),
    }


def _build_report_outline(report_markdown: str | None) -> list[dict[str, Any]]:
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


def _build_report_chart(
    *,
    metrics_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any] | None:
    provider_counts = report_payload.get("provider_counts")
    bars: list[dict[str, Any]] = []
    accents = ("primary", "secondary", "tertiary")
    if isinstance(provider_counts, dict):
        for index, (label, value) in enumerate(provider_counts.items()):
            numeric = _read_int(value)
            if numeric is None:
                continue
            bars.append(
                {
                    "label": str(label).strip(),
                    "value": numeric,
                    "accent": accents[index % len(accents)],
                }
            )
            if len(bars) >= 3:
                break
    if not bars:
        quality_payload = metrics_payload.get("quality")
        if isinstance(quality_payload, dict):
            fallback_pairs = [
                ("引用数", quality_payload.get("citation_count")),
                ("关键发现", quality_payload.get("finding_count")),
            ]
            for index, (label, value) in enumerate(fallback_pairs):
                numeric = _read_int(value)
                if numeric is None:
                    continue
                bars.append(
                    {
                        "label": label,
                        "value": numeric,
                        "accent": accents[index % len(accents)],
                    }
                )
    if not bars:
        return None
    return {"title": "研究覆盖概览", "bars": bars}


def _build_report_spotlight_cards(
    *, source_ledger_payload: list[dict[str, Any]]
) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for item in source_ledger_payload[:2]:
        eyebrow = str(item.get("provider") or "").strip() or "重点对象"
        title = "关键参与者"
        description = str(item.get("title") or item.get("origin_url") or "").strip()
        if not description:
            continue
        cards.append(
            {
                "eyebrow": eyebrow,
                "title": title,
                "description": description,
            }
        )
    return cards


def _build_report_outlook_cards(*, report_payload: dict[str, Any]) -> list[dict[str, str]]:
    findings = report_payload.get("findings")
    if not isinstance(findings, list):
        return []
    normalized = [
        str(item).strip()
        for item in findings
        if isinstance(item, str) and str(item).strip()
    ]
    source_items = normalized[2:4] if len(normalized) >= 4 else normalized[:2]
    return [
        {
            "title": f"研究启示 {index:02d}",
            "description": item,
        }
        for index, item in enumerate(source_items, start=1)
    ]


def _build_report_references(
    *,
    report_payload: dict[str, Any],
    source_ledger_payload: list[dict[str, Any]],
) -> list[str]:
    references: list[str] = []
    citations = report_payload.get("citations")
    if isinstance(citations, list):
        for index, item in enumerate(citations, start=1):
            if not isinstance(item, dict):
                continue
            title = str(
                item.get("title")
                or item.get("source_id")
                or item.get("origin_url")
                or ""
            ).strip()
            if not title:
                continue
            references.append(f"{index:02d}. {title}")
    if references:
        return references
    for index, item in enumerate(source_ledger_payload, start=1):
        title = str(item.get("title") or item.get("origin_url") or "").strip()
        if not title:
            continue
        references.append(f"{index:02d}. {title}")
    return references
