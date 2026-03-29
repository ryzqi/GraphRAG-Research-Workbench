# Task Todo - Fine

## Project / Phase Context
- Roadmap File / Reference: `full-refactor-deep-research/PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-4-frontend-workbench.md`
  - `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-4-frontend-workbench.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files:
  - `PROJECT_PHASE_ROADMAP.md`
  - `TASK_TODO_MEDIUM.md`
  - `TASK_TODO_FINE.md`
  - `PROJECT_EXECUTION_STATE.md`
- Current Phase: Phase 5 - 可观测、文档同步与最终交付门禁
- Current Phase Inputs:
  - Task 10 提交：`a262b17 feat(research): add research workbench panels`
  - Task 11 当前工作树产物：observability / gate / replay / rollback / interrupt-resume E2E
  - 当前 research runtime 约束：`create_deep_agent` 单入口、`subgraphs=True`、`version="v2"`、无 MCP
- Active Execution Wave: Task 11 已完成；下一任务 = Task 12 docs sync
- Phase Goal: 完成 Task 12（文档与契约同步）
- Phase Scope:
  - 包含：proposal / design / docs / README / spec 的术语统一
  - 不包含：Task 13 全量启动验证
- Non-goals:
  - 不恢复旧 run-centric 研究接口
  - 不在此轮追加新 runtime 功能

## Part 1: 已完成任务收口
### 1.1 Task 11 交付闭环
- [x] Task: 先红后绿完成 observability / gate / replay / rollback / interrupt-resume E2E
- Goal: 让研究链路具备最小发布门禁
- Inputs / Dependencies:
  - `backend/src/app/services/research_service.py`
  - `backend/src/app/worker/tasks/research.py`
  - `backend/src/app/schemas/research.py`
  - `frontend/src/types/researchEvents.ts`
- Output / Artifact:
  - `research_observability.py`
  - `research_replay.py`
  - `metrics_snapshot` / `gate_snapshot`
  - rollback drill 脚本 / runbook / 记录
- Done when:
  - `uv run pytest tests/research tests/api/test_research_endpoints.py -q` -> `48 passed`
  - `uv run ruff check ...` -> `All checks passed!`
  - `npm run typecheck` -> `passed`
- Notes:
  - 研究事件封套已补 `lc_agent_name`
  - 失败路径已落 `research.run.failed` + fault metrics

## Part 2: 当前阶段研究与拆解
### 2.1 Task 12 文档扫描
- [ ] Task: 扫描 `proposal.md`、`design.md`、`README.md`、`docs/*`、`specs/*/spec.md` 中的旧 research 术语
- Goal: 找出所有 run-centric / 旧兼容表述
- Inputs / Dependencies:
  - `full-refactor-deep-research/tasks.md`
  - `backend/src/app/schemas/research.py`
  - `backend/src/app/services/research_observability.py`
  - `scripts/research_rollback_drill.ps1`
- Output / Artifact: Task 12 文档更新清单
- Done when: 需要更新的文件与术语映射明确
- Notes: 以当前代码、Task 11 门禁与 rollback 产物为唯一事实源

### 2.2 Task 12 写作顺序
- [ ] Task: 先更新 contract / API / gate 文档，再更新 README / proposal / design / specs
- Goal: 让高优先级事实源先统一
- Procedure / Implementation notes:
  - 先写 `docs/api_contract_research.md`
  - 再同步 proposal / design 的 phase / task / gate 描述
  - 最后回扫 README 与 specs 中旧术语残留
- Done when: 下一轮可按文件波次执行
- Notes: 文档更新后需做最小 grep / 交叉校对

## Part 3: 当前阶段执行
### 3.1 下一轮首个执行波次
- [ ] Task: 建立 Task 12 的旧术语 -> 新术语映射表
- Goal: 降低“文档写法不同步”的风险
- Output / Artifact:
  - `run_id` -> `session_id`
  - `/api/v1/research/runs*` -> `/api/v1/research/sessions*`
  - old run-centric runtime -> current Deep Agents runtime
  - ad-hoc export path -> `research_artifacts` / `metrics_snapshot` / `gate_snapshot`
- Done when: 可直接驱动文档批量替换与人工校对

### 3.2 下一轮验证基线
- [ ] Task: Task 12 完成后跑最小文档一致性检查
- Goal: 防止更新后仍残留旧术语
- Verification:
  - `rg -n "/api/v1/research/runs|run-centric|run_id" full-refactor-deep-research README.md docs backend frontend`
  - 必要时补充定向测试 / typecheck
- Done when: 文档与代码术语一致
