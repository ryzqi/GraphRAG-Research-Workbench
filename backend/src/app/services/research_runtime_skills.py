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

1. Read mission, plan, query-map, coverage, claim-map, evidence-ledger, analysis-notes, report-outline, and report-draft before any external search.
2. Call `write_todos` immediately after reading the scaffold. Todos must cover claims, coverage gaps, subagent delegation, and report completion.
3. Update claim-map, evidence-ledger, analysis-notes, report-outline, and report-draft continuously during the run.
4. Use external search only to close unresolved claims, cross-check evidence, or remove coverage gaps.
5. Return concise structured findings and citations instead of raw tool dumps.
""",
        "/skills/research-reporting/SKILL.md": """---
name: research-reporting
description: Use this skill when consolidating citations, report outline, and runtime context for the final deep research report.
---

# research-reporting

1. Validate claim-to-citation mapping before drafting conclusions.
2. Keep report-outline and report-draft aligned with verified findings only.
3. Persist report-context.json with executive summary, conflicts, open questions, confidence level, and citation coverage.
4. Keep the output audit-friendly and explicit about unresolved gaps.
""",
    }
