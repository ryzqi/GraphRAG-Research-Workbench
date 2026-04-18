"""Deep Research runtime 的 run-scoped skills。"""

from __future__ import annotations


def build_research_runtime_skill_files() -> dict[str, str]:
    """返回 DeepAgents 运行时需要注入的技能文件。"""

    return {
        "/skills/research-runtime/SKILL.md": """---
name: research-runtime
description: Use this skill for deep research runtime tasks that require claim-first planning, write_todos, coverage tracking, and file-based context management.
---

# research-runtime

1. Maintain `task-graph.json`, `claim-bundles.json`, `section-briefs.json`, and `report-context.json` as the runtime handoff surface so the main agent can offload context to files instead of carrying everything inline.
2. Call `write_todos` immediately after reading the scaffold. The first `plan.subtasks` todo items must use the format `[plan-step-<index>] <title>` and stay aligned one-to-one with the planner subtasks. Additional todos should cover claims, coverage gaps, subagent delegation, and report completion.
3. 先创建动态全文大纲：根据研究主题、用户补充、research brief 与 plan subtasks，先写好 `report-outline` 和每个 section 的简短写作说明，再进入补证与扩写。
4. `report-outline` 与 `report-draft` 的章节标题统一使用 `## [section-id] 章节标题` 格式，`section-id` 必须与 `section-briefs.json` 中的条目一致。
5. Refine `task-graph.json` first, then delegate bounded work via `task` to the best subagent. If web and paper evidence can be collected independently, dispatch them as parallel siblings under the same `parallel_group`.
6. Before any `web_search`, `arxiv_*`, or `task` call, confirm the outline gate is satisfied: `report-outline` is complete, `section-briefs.json` is complete, and `report-context.json` records the active outline state.
7. Before every `task` call, prepare a handoff packet in `task-graph.json`, `claim-bundles.json`, or `section-briefs.json`: objective, claim, evidence requirements, files to read, files to update, and success criteria. The subagent request should reference that handoff packet explicitly.
8. Keep `report-context.json` updated with `executive_summary`, `key_takeaways`, `recommended_actions`, `verification_notes`, `open_questions`, `section_status`, outline status, and confidence/conflict fields.
9. Keep the `[plan-step-<index>]` todo statuses updated as you progress through planner subtasks. `plan_progress_snapshot` is derived from these todos; do not invent a second plan-progress channel.
10. `live-board.json` is a projection for runtime observability, not the single source of truth for planning state. Whenever the active task, active agent, or parallel workset changes, call `record_runtime_activity(...)` so the frontend can update that projection.
11. Update claim-map, evidence-ledger, analysis-notes, report-outline, report-draft, section briefs, claim bundles, and report context continuously during the run.
12. Return concise structured findings and citations instead of raw tool dumps.
""",
        "/skills/research-reporting/SKILL.md": """---
name: research-reporting
description: Use this skill when consolidating citations, report outline, and runtime context for the final deep research report.
---

# research-reporting

1. Validate claim-to-citation mapping before drafting conclusions.
2. Build section-level briefs before long-form drafting. Each brief should summarize the section, evidence, unresolved gaps, and citation indices.
3. Keep report-outline and report-draft aligned with verified findings only.
4. Persist report-context.json with executive summary, key takeaways, recommended actions, verification notes, conflicts, open questions, confidence level, section status, and citation coverage.
5. Every section handoff should point to the exact claim bundle and evidence ledger entries it relies on.
6. Keep the output audit-friendly and explicit about unresolved gaps.
""",
    }
