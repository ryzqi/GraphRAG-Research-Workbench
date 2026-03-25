"""用于 KB Chat 实时运行的 SSE 解析与 Markdown 工件渲染辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedSseEvent:
    event: str
    data: str
    payload: Any


def _parse_sse_block(block: str) -> ParsedSseEvent | None:
    event = "message"
    data_lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.rstrip("\r")
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            value = line[6:].strip()
            event = value or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))

    if not data_lines:
        return None

    data = "\n".join(data_lines)
    try:
        payload: Any = json.loads(data)
    except json.JSONDecodeError:
        payload = data
    return ParsedSseEvent(event=event, data=data, payload=payload)


def parse_sse_text(raw: str) -> list[ParsedSseEvent]:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = normalized.split("\n\n")
    events: list[ParsedSseEvent] = []
    for block in blocks:
        if not block.strip():
            continue
        event = _parse_sse_block(block)
        if event is not None:
            events.append(event)
    return events


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False)


def _render_display_items(payload: dict[str, Any]) -> list[str]:
    items = payload.get("display_output_items")
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        value = _stringify_value(item.get("value"))
        if not label or not value:
            continue
        lines.append(f"- {label}: {value}")
    return lines


def _extract_final_answer(events: list[ParsedSseEvent]) -> str:
    for event in reversed(events):
        if not isinstance(event.payload, dict):
            continue
        payload = event.payload
        if event.event == "final":
            for key in ("answer", "final_answer"):
                value = _stringify_value(payload.get(key))
                if value:
                    return value
        if event.event == "node_io" and payload.get("node_name") in {"answer_commit", "force_exit"}:
            for key in ("final_answer", "draft_answer"):
                value = _stringify_value(payload.get(key))
                if value:
                    return value
    return ""


def render_case_markdown(
    *,
    case_id: str,
    question: str,
    expected_strategy: str,
    expected_answer: str,
    events: list[ParsedSseEvent],
) -> str:
    lines = [
        f"# {case_id}",
        "",
        "## 问题",
        "",
        question.strip(),
        "",
        "## 预期",
        "",
        f"- 预期策略: `{expected_strategy.strip()}`",
        f"- 标准答案要点: {expected_answer.strip()}",
        "",
        "## 关键节点输出",
        "",
    ]

    node_lines_added = False
    for event in events:
        if event.event != "node_io" or not isinstance(event.payload, dict):
            continue
        payload = event.payload
        node_name = str(payload.get("node_name") or payload.get("node_id") or "").strip()
        phase = str(payload.get("phase") or "").strip() or "unknown"
        if not node_name:
            continue
        lines.append(f"### {node_name} · {phase}")
        lines.append("")
        display_lines = _render_display_items(payload)
        if display_lines:
            lines.extend(display_lines)
        else:
            lines.append("```json")
            lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")
        node_lines_added = True

    if not node_lines_added:
        lines.extend(["- 未捕获到 node_io 事件。", ""])

    final_answer = _extract_final_answer(events)
    lines.extend(
        [
            "## 最终答案",
            "",
            final_answer or "（未捕获最终答案）",
            "",
        ]
    )
    return "\n".join(lines)
