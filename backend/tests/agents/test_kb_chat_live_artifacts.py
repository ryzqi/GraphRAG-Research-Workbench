from __future__ import annotations

from app.services.kb_chat_live_artifacts import parse_sse_text, render_case_markdown


def test_parse_sse_text_ignores_comment_heartbeat_and_parses_json_payloads() -> None:
    raw = (
        ": keep-alive\n\n"
        "event: meta\n"
        'data: {"run_id":"r1","type":"kb_chat"}\n\n'
        "event: node_io\n"
        'data: {"node_name":"query_plan","phase":"end","display_output_items":[{"label":"策略","value":"direct"}]}\n\n'
    )

    events = parse_sse_text(raw)

    assert [event.event for event in events] == ["meta", "node_io"]
    assert events[0].payload == {"run_id": "r1", "type": "kb_chat"}
    assert events[1].payload["node_name"] == "query_plan"
    assert events[1].payload["display_output_items"] == [{"label": "策略", "value": "direct"}]


def test_render_case_markdown_renders_question_strategy_nodes_and_final_answer() -> None:
    raw = (
        "event: meta\n"
        'data: {"run_id":"r1","type":"kb_chat"}\n\n'
        "event: node_io\n"
        'data: {"node_name":"query_plan","phase":"end","display_output_items":[{"label":"策略","value":"direct"},{"label":"说明","value":"问题简单，直接检索"}]}\n\n'
        "event: final\n"
        'data: {"answer":"CoT 适合单路径、步骤明确的推理任务。","stage_summaries":{"query_plan":{"strategy":"direct"}}}\n\n'
    )

    markdown = render_case_markdown(
        case_id="case_direct",
        question="CoT 适合什么场景？",
        expected_strategy="direct",
        expected_answer="CoT 更适合单路径、步骤明确的推理任务。",
        events=parse_sse_text(raw),
    )

    assert "# case_direct" in markdown
    assert "## 问题" in markdown
    assert "CoT 适合什么场景？" in markdown
    assert "## 预期" in markdown
    assert "- 预期策略: `direct`" in markdown
    assert "## 关键节点输出" in markdown
    assert "### query_plan · end" in markdown
    assert "- 策略: direct" in markdown
    assert "- 说明: 问题简单，直接检索" in markdown
    assert "## 最终答案" in markdown
    assert "CoT 适合单路径、步骤明确的推理任务。" in markdown
