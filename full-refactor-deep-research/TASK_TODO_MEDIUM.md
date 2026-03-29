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
- Customer Problem / Desired Outcome: 在主链路与文档事实源都已统一后，完成最终全量验证、demo 与启动 smoke，确保可以诚实宣称当前 Deep Research 主路径可交付。
- Why Now / Decision Driver: Task 12 已同步文档与 demo 入口；若不继续完成 Task 13，全量测试、build 与启动结论仍然缺失。
- Current Phase: Phase 5 - 可观测、文档同步与最终交付门禁
- Phase Goal: 完成 Task 13（最终验证与交付门禁）
- Phase Scope:
  - 包含：backend 全量 `pytest` / `ruff`、frontend `typecheck` / `build`、demo script 实跑、启动 smoke、gate 结论收口
  - 不包含：新的 runtime 结构改造；除非验证失败，否则不再扩展文档范围
- Non-goals:
  - 不恢复旧 `/api/v1/research/runs*`
  - 不在此轮做新的 runtime 功能扩张
- Phase Deliverables:
  - backend / frontend 全量验证证据
  - demo script 实跑证据
  - 启动 smoke 与 gate 决议记录
- Active Execution Wave: Task 13 已完成验证，待提交当前收口补丁
- Entry Criteria:
  - Phase 4 已完成
  - Task 11 trace / metrics / gate / replay / rollback 已验证并提交
  - Task 12 文档与 demo 入口已同步
- Exit Criteria / Done Definition:
  - Task 13 全量验证完成并提交
  - backend 全量测试与 ruff 通过
  - frontend typecheck 与 build 通过
  - demo script 与启动验证通过，并形成 gate 结论

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

### 1.3 Task 12 完成记录
- [x] Task: 同步 proposal / design / specs / README / docs / demo script 到当前 research session contract
- Goal: 让 Task 13 的最终验证以单一路径事实源为准
- Done when:
  - README / architecture / API contract 均指向 `/api/v1/research/sessions*`
  - demo script 指向当前会话化接口
  - Deep Agents 文档快照已明确“无顶层 `subagent_model`，子代理模型落到 `subagents[*].model`”
- Deliverables:
  - `README.md`
  - `docs/api_contract_research.md`
  - `docs/architecture.md`
  - `full-refactor-deep-research/proposal.md`
  - `full-refactor-deep-research/design.md`
  - `full-refactor-deep-research/tasks.md`
  - `full-refactor-deep-research/deepagents-latest-usage-2026-03-26.md`
  - `full-refactor-deep-research/deepagents-implementation-analysis-2026-03-26.md`
  - `full-refactor-deep-research/specs/*/spec.md`
  - `scripts/demo_research.ps1`
- Verification:
  - `pwsh -ExecutionPolicy Bypass -File .\scripts\demo_research.ps1 -DryRun` -> 输出当前会话化流程
  - `rg -n "0\.5\.0a2|s\.jina\.ai|/api/v1/research/runs\*|/api/v1/research/runs|run_id\b|create_deep_agent\([^\n]*subagent_model|subagent_model=" ...` -> 仅剩有意保留的否定说明与 `gate_run_id`
  - `uv run python -c "import inspect; from deepagents import create_deep_agent; print(inspect.signature(create_deep_agent))"` -> 不含顶层 `subagent_model`

## Part 2: 当前阶段目标
### 2.1 锁定 Task 13 目标
- [x] Task: 将 active todo 切换到 `tasks.md` Task 13（最终验证与交付门禁）
- Goal: 用 fresh verification 证明当前主路径可启动、可验证、可交付
- Done when: Phase 5 当前执行波次与 Task 13 边界清晰
- Deliverables: Task 13 执行目标
- Notes: 继续保持“一次只完成一个任务”

## Part 3: 当前阶段研究与计划
### 3.1 Task 13 输入事实源
- [x] Task: 固定当前验证矩阵与命令顺序
- Goal: 避免在最终收口阶段遗漏 backend / frontend / demo / startup 任一关键环节
- Done when: Task 13 验证矩阵明确
- Deliverables:
  - backend：`uv run pytest`、`uv run ruff check .`
  - frontend：`npm run typecheck`、`npm run build`
  - demo / startup：`scripts/demo_research.ps1`、实际启动链路
- Notes:
  - 实际执行结果：
    - `cd backend; uv run pytest` -> `78 passed`
    - `cd backend; uv run ruff check .` -> `All checks passed!`
    - `cd frontend; npm run typecheck` -> `passed`
    - `cd frontend; npm run build` -> `passed`
    - `pwsh -ExecutionPolicy Bypass -File .\scripts\demo_research.ps1 -BaseUrl http://127.0.0.1:8000 -TimeoutSec 90` -> 成功跑通
    - `http://127.0.0.1:8000/api/v1/ready` / `/docs` / `http://127.0.0.1:3000` -> `200`

### 3.2 Task 13 执行顺序
- [x] Task: 采用“backend 全量 -> frontend 构建 -> demo -> 启动 smoke -> gate 决议 -> 提交”顺序
- Goal: 让失败定位保持单向收敛，避免混淆根因
- Done when: 下一轮执行顺序稳定
- Notes:
  - 实际失败与修复：
    - `ResearchArtifactStore` 真实 DB 下访问未预加载 relationship 触发 `MissingGreenlet` -> 已补显式查询与回归测试
    - Celery research 任务原先错误路由到 `default` 队列 -> 已改到 `research` 队列并补测试
    - worker research task 原先未装配 runtime_runner -> 已接入 `build_deep_research_runtime_runner`
    - OpenAI `previous_response_id` 404 导致 runtime fail -> 已在 Deep Research runtime 显式禁用 `use_previous_response_id`
  - gate 结论：
    - `gate_snapshot.pass = true`
    - `quality_score = 0.825`
    - `p95_ms = 19549`
    - `session_cost_usd = 0.0`
    - 当前 demo 工件 provider 统计为 `workspace`
