"""Deep Research runtime 的 run-scoped skills。"""

from __future__ import annotations


def build_research_runtime_skill_files() -> dict[str, str]:
    """返回 DeepAgents 运行时需要注入的技能文件。"""

    return {
        "/skills/research-runtime/SKILL.md": """---
name: research-runtime
description: Use this skill for deep research runtime tasks that follow the breadth -> depth -> critic pipeline with LLM alignment gating.
---

# research-runtime

1. Pipeline 强制顺序：breadth-pass -> breadth gate -> outline/section-briefs -> depth-pass -> draft-pass -> critic-pass -> finalize-pass。
2. 事实源（JSON）只使用 canonical path：04-claim-map.json / 05-evidence-ledger.json / 07-claim-bundles.json / 08-section-briefs.json / report-context.json / 06-task-graph.json。具体 session 绝对路径以 context guide / handoff 为准；禁止自行拼接模板路径或改用旧别名。md 文件仅作为投影。
3. 每个子代理委派前，在 task-graph.json、claim-bundles.json 或 section-briefs.json 写 handoff packet（claim_id / objective / 必读 / 必写 / 成功判据）。
4. critic-pass 必须调用 evidence-critic + coverage-critic 各一次；读取 handoff 提供的 evidence-critique.json / coverage-critique.json 实际绝对路径决定是否回流。最多回流 2 次。
5. breadth gate、critic-pass 与 finalize-pass 分别对应代码中的硬 gate（breadth gate / critic_revise_max_passes / structured_response 校验）。
6. [plan-step-<index>] todos 与 plan.subtasks 一一对应；plan_progress_snapshot 由它们推导。
7. 每次 active task / agent / parallel group 变化时调用 record_runtime_activity(...)。
8. 工件写入遵循 shared_contract：findings >= 2、citations >= 2 且每条附 excerpts（40-400 字）。
9. `05-evidence-ledger.json` 的顶层键是 `evidences`，不是 `evidence_entries`；不要写裸文件名或无编号别名路径。
""",
        "/skills/research-reporting/SKILL.md": """---
name: research-reporting
description: Use this skill when consolidating citations, outline, and context into the final deep research report.
---

# research-reporting

1. finalize 前 citation-steward 必须审计：provider id 规范、excerpts 存在、workspace url scheme、orphan 处理。
2. report-outline 与 report-draft 标题统一 `## [section-id] 章节标题`，与 section-briefs 对齐。
3. 仅消费 status == supported / contested 的 claim；insufficient 的 claim 只能作为"开放问题"段落。
4. report-context.json 维护：executive_summary / key_takeaways / recommended_actions / verification_notes / open_questions / section_status / confidence_level / has_conflicts / outline_ready / outline_status。
5. 最终 structured_response 的 findings / citations 必须与 report-draft 中引用编号一致；不得互相脱节。
""",
    }
