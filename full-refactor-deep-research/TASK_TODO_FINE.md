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
  - Task 11 提交：`d5448a3 feat(research): add observability gates and replay coverage`
  - Task 12 当前工作树产物：文档 / specs / README / demo script 同步
  - 当前 research runtime 约束：`create_deep_agent` 单入口、`subgraphs=True`、`version="v2"`、无 MCP
- Active Execution Wave: Task 13 已完成验证，待提交当前收口补丁
- Phase Goal: 完成 Task 13（最终验证与交付门禁）
- Phase Scope:
  - 包含：backend 全量 `pytest` / `ruff`、frontend `typecheck` / `build`、demo script、启动 smoke、gate 决议
  - 不包含：新的 runtime 功能扩展；除非验证失败，否则不继续扩改文档
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

### 1.2 Task 12 文档同步闭环
- [x] Task: 完成当前 research session contract 文档、spec 与 demo 入口同步
- Goal: 让 Task 13 只围绕当前单路径事实源做验证
- Inputs / Dependencies:
  - `README.md`
  - `docs/api_contract_research.md`
  - `docs/architecture.md`
  - `full-refactor-deep-research/proposal.md`
  - `full-refactor-deep-research/design.md`
  - `full-refactor-deep-research/tasks.md`
  - `full-refactor-deep-research/specs/*/spec.md`
  - `scripts/demo_research.ps1`
- Output / Artifact:
  - session contract 文档
  - Deep Agents 最新用法快照
  - demo script dry-run 入口
- Done when:
  - dry-run 能打印当前 `/api/v1/research/sessions*` 全流程
  - 文档不再误写 `create_deep_agent(..., subagent_model=...)`
  - docs/spec/README 统一引用 `metrics_snapshot` / `gate_snapshot`
- Notes:
  - Deep Agents 当前安装签名已 fresh verify：无顶层 `subagent_model`

## Part 2: 当前阶段研究与拆解
### 2.1 Task 13 验证矩阵
- [x] Task: 固定 backend / frontend / demo / startup 的最终验证矩阵
- Goal: 保证收口阶段的验证顺序稳定、无遗漏
- Inputs / Dependencies:
  - `full-refactor-deep-research/tasks.md`
  - `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
  - `scripts/demo_research.ps1`
- Output / Artifact: Task 13 验证矩阵
- Done when: backend / frontend / demo / startup 全部有明确命令
- Notes: 以当前代码、Task 11 门禁与 Task 12 文档事实源为唯一事实源

### 2.2 Task 13 执行顺序
- [x] Task: 采用“backend 全量 -> frontend 构建 -> demo -> 启动 smoke -> gate 决议”顺序
- Goal: 保持根因定位单向收敛
- Procedure / Implementation notes:
  - 先跑 backend，保证核心服务契约稳定
  - 再跑 frontend，避免前端构建失败掩盖后端问题
  - 再做 demo 与启动 smoke，验证真实链路
- Done when: 下一轮可按验证波次执行
- Notes: 任一步失败都必须先修复，再继续下一步

## Part 3: 当前阶段执行
### 3.1 下一轮首个执行波次
- [x] Task: 执行 backend 全量验证
- Goal: 先确认 research 主链路与测试基线无回归
- Output / Artifact:
  - `cd backend; uv run pytest`
  - `cd backend; uv run ruff check .`
- Done when: backend 两条命令都有 fresh 结果
- Notes:
  - `uv run pytest` -> `78 passed`
  - `uv run ruff check .` -> `All checks passed!`

### 3.2 下一轮验证基线
- [x] Task: backend 通过后执行 frontend / demo / 启动 smoke
- Goal: 证明 workbench、demo 与真实启动链路都与当前 session contract 对齐
- Verification:
  - `cd frontend; npm run typecheck`
  - `cd frontend; npm run build`
  - `pwsh -ExecutionPolicy Bypass -File .\scripts\demo_research.ps1`
  - 实际启动链路 smoke
- Done when: 全链路验证完成，且可汇总 gate 决议
- Notes:
  - `npm run typecheck` -> `passed`
  - `npm run build` -> `passed`
  - `pwsh -ExecutionPolicy Bypass -File .\scripts\demo_research.ps1 -BaseUrl http://127.0.0.1:8000 -TimeoutSec 90`
    - session_id=`efecfe8c-2600-4e7d-84c9-1d48f3ea7a43`
    - 最终事件序列：`research.plan.created` -> `research.plan.confirmed` -> `research.run.started` -> `research.finalizer.started` -> `research.final.completed`
    - artifacts：`coverage_gaps`、`gate_snapshot`、`interim_findings`、`interim_summary`、`metrics_snapshot`、`plan_snapshot`、`report_json`、`report_md`、`research_brief`、`source_bundle`
  - 启动 smoke：
    - `http://127.0.0.1:8000/api/v1/ready` -> `200`
    - `http://127.0.0.1:8000/docs` -> `200`
    - `http://127.0.0.1:3000` -> `200`
  - gate：
    - `gate_snapshot.pass = true`
    - `quality_score = 0.825`
    - `p95_ms = 19549`
    - `session_cost_usd = 0.0`
