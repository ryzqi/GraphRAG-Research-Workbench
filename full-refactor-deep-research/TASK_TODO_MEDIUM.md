# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `full-refactor-deep-research/PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-1-foundation.md`
  - `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-1-foundation.md`
  - `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-4-frontend-workbench.md`
  - `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-4-frontend-workbench.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files:
  - `PROJECT_PHASE_ROADMAP.md`
  - `TASK_TODO_MEDIUM.md`
  - `TASK_TODO_FINE.md`
  - `PROJECT_EXECUTION_STATE.md`
- Project Modules: Deep Agents runtime；source-aware tooling；service / persistence orchestration；API / worker / export；frontend workbench；observability / docs / release gate
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 在主链路已打通的基础上，继续把文档、契约与最终交付门禁统一到当前 `session_id` 单路径 research 事实源。
- Why Now / Decision Driver: Task 11 已补齐 observability / replay / rollback，但若文档不同步，Task 13 的最终验证与交付结论仍会失真。
- Current Phase: Phase 5 - 可观测、文档同步与最终交付门禁
- Phase Goal: 完成 Task 12（文档与契约同步）
- Phase Scope:
  - 包含：`proposal.md`、`design.md`、`README.md`、research API contract docs、demo script 文档入口
  - 不包含：Task 13 的全量测试 / build / 启动实跑
- Non-goals:
  - 不恢复旧 `/api/v1/research/runs*`
  - 不在此轮做新的 runtime 结构改造
- Phase Deliverables:
  - 当前研究单路径术语统一文档
  - `docs/api_contract_research.md`
  - Task 11 observability / gate / replay / rollback 文档锚点
- Active Execution Wave: Task 11 已完成；下一任务 = Task 12 docs sync
- Entry Criteria:
  - Phase 4 已完成
  - Task 11 trace / metrics / gate / replay / rollback 已验证
- Exit Criteria / Done Definition:
  - Task 12 文档同步完成并提交
  - 所有文档统一使用当前 research session contract 术语
  - Task 13 可直接据此执行全量验证

## Part 1: 已完成任务收口
### 1.1 Task 10 完成记录
- [x] Task: 前端 workbench 已接入 plan preview / timeline / interrupt / artifact panels
- Goal: 完成 planner -> confirm -> runtime -> interrupt -> resume -> final 的前端可视化工作台
- Done when: `a262b17 feat(research): add research workbench panels` 已提交且对应 Vitest / typecheck 通过
- Notes:
  - 当前页面已 hard cut 到 session/event/artifact 契约
  - 网页 / 论文证据差异化展示已接通

### 1.2 Task 11 完成记录
- [x] Task: 落地 observability / gate / replay / rollback / interrupt-resume E2E
- Goal: 为最终交付建立最小可信门禁
- Done when:
  - `trace_id / session_id / lc_agent_name / namespace` 贯通
  - `metrics_snapshot` / `gate_snapshot` 工件落盘
  - 故障注入、事件回放、interrupt-resume E2E 测试通过
  - rollback drill 记录已生成
- Deliverables:
  - `backend/src/app/services/research_observability.py`
  - `backend/src/app/services/research_replay.py`
  - `backend/tests/research/test_research_observability.py`
  - `backend/tests/research/test_research_fault_injection.py`
  - `backend/tests/research/test_research_event_replay.py`
  - `backend/tests/research/test_e2e_interrupt_resume_contract.py`
  - `scripts/research_rollback_drill.ps1`
  - `full-refactor-deep-research/research-rollback-runbook.md`
  - `full-refactor-deep-research/research-rollback-drill-record.md`
- Verification:
  - `uv run pytest tests/research tests/api/test_research_endpoints.py -q` -> `48 passed`
  - `uv run ruff check ...` -> `All checks passed!`
  - `npm run typecheck` -> `passed`
- Notes:
  - 默认 gate 阈值：quality `0.75` / p95 `120000ms` / session cost `2.0 USD`
  - rollback drill 当前为 dry-run，不执行破坏性 git / service 操作

## Part 2: 当前阶段目标
### 2.1 锁定 Task 12 目标
- [x] Task: 将 active todo 切换到 `tasks.md` Task 12（文档与契约同步）
- Goal: 让后续工作以文档事实源驱动，不再混用旧术语
- Done when: Phase 5 当前执行波次与 Task 12 边界清晰
- Deliverables: Task 12 执行目标
- Notes: 继续保持“一次只完成一个任务”

## Part 3: 当前阶段研究与计划
### 3.1 Task 12 输入事实源
- [ ] Task: 汇总当前 docs / specs / README / design 中仍引用旧 research 术语的段落
- Goal: 锁定需要同步的文档范围
- Done when: Task 12 文档清单明确
- Deliverables:
  - `proposal.md`
  - `design.md`
  - `README.md`
  - `docs/api_contract_research.md`
  - `specs/*/spec.md`
- Notes: 以当前代码与 Task 11 产物为唯一事实源

### 3.2 Task 12 执行顺序
- [ ] Task: 采用“盘点旧术语 -> 更新文档 -> 交叉校对 API / gate / rollback 表述 -> 定向验证 -> 提交”顺序
- Goal: 保持文档更新与当前实现一致
- Done when: 下一轮执行顺序稳定
- Notes: Task 12 完成后进入 Task 13 全量验证
