# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `full-refactor-deep-research/PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-1-foundation.md`
  - `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-1-foundation.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files:
  - `PROJECT_PHASE_ROADMAP.md`
  - `TASK_TODO_MEDIUM.md`
  - `TASK_TODO_FINE.md`
  - `PROJECT_EXECUTION_STATE.md`
- Project Modules: Deep Agents runtime 与 source-aware tooling；契约与会话编排
- Brownfield Context / Codebase Map:
  - Phase 1 已完成并提交：`research_sessions / research_events / research_artifacts` 三表、`schemas/research.py`、`research_planner.py`
  - backend 已锁定 `deepagents==0.4.12`，并通过本地签名核对 `create_deep_agent(..., skills, memory, checkpointer, store, backend, interrupt_on, subagents)` 当前 API
  - runtime 相关旧 research 服务/路由仍为空白，需要从最新官方 Deep Agents 用法直接 hard cut 新实现
  - 需重点关注：`backend/src/app/agents/tool_calling/registry.py`、`backend/src/app/services/*`、`full-refactor-deep-research/design.md`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 把 Phase 1 的业务壳层接到唯一的 Deep Agents runtime harness，上游不再停留在“只有模型和契约”的半成品状态
- Why Now / Decision Driver: 若不先完成 runtime 单入口与来源路由，后续 ResearchService / API / 前端都无法真正联通
- Phase Roadmap Summary: 先完成 Task 4 runtime skeleton 与依赖锁定，再做 Task 5 source-aware routing，最后做 Task 6 service/persistence orchestration
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Phase Goal: 完成 Task 4-6 的 runtime/service 主骨架，当前先完成 Task 4（Deep Agents 单引擎运行时）
- Phase Scope:
  - 包含：Deep Agents 依赖策略、runtime types、`create_deep_agent` 单入口、后端分层、研究模式工具装配约束、Task 4 测试
  - 不包含：Task 7+ 当前 API / 前端改造
- Non-goals:
  - 不保留旧 research engine / run-centric fallback
  - 不在本轮把所有 API/worker/frontend 一并接上
- Phase Deliverables:
  - `backend/src/app/services/deep_research_runtime.py`
  - `backend/src/app/services/research_runtime_types.py`
  - 运行时依赖与装配策略
  - `backend/tests/research/test_deep_research_runtime.py`
- Active Execution Wave: Task 4 已完成；下一任务 = Task 5 source-aware routing
- Entry Criteria:
  - Phase 1 三个任务已提交：`0c5fa63` / `efc6693` / `c3ccdf2`
  - 最新官方 Deep Agents 文档已核对，`create_deep_agent` / `stream(... version="v2", subgraphs=True)` / `interrupt_on + checkpointer` 为当前约束
- Exit Criteria / Done Definition:
  - Task 4 代码与测试完成并提交
  - 已锁定 `deepagents` 依赖策略，且 runtime 只保留单入口
  - 定向 pytest / ruff 通过
- Transition Notes / Next Phase Trigger: Task 4 提交后继续在 Phase 2 内推进 Task 5（source-aware routing）
- Previous Phase Summary: Phase 1 已完成 Task 1-3，输出三表、schema 契约与 preflight planner，并归档旧 todo

## Part 1: 当前阶段需求与范围
### 1.1 锁定 Task 4 目标
- [x] Task: 将 `tasks.md` Task 4 重写为可执行 runtime 目标
- Goal: 明确本轮先解决依赖、runtime 单入口与中间件/后端装配，不抢跑 service/API
- Done when: Task 4 边界与验收清晰
- Deliverables: 当前执行目标说明
- Notes: 以 `create_deep_agent` 为唯一运行时入口

### 1.2 确认 Task 4 约束与依赖
- [x] Task: 汇总 Deep Agents 版本策略、现有 langchain/langgraph 依赖、研究模式工具装配入口与测试面
- Goal: 避免运行时实现与依赖版本失配
- Done when: 约束、依赖、风险已记录
- Deliverables: 当前约束摘要
- Notes: 已选用 stable `deepagents==0.4.12`；当前 0.4.12 实际签名已覆盖 Task 4 所需 API，无需切到 pre-release

## Part 2: 当前阶段研究与计划
### 2.1 复核 Task 4 上下文
- [x] Task: 审查 `pyproject.toml`、tool registry、Phase 1 输出、官方 Deep Agents customization/backends/streaming 文档
- Goal: 让 runtime 设计与本地 baseline、一手文档一致
- Done when: 当前 task 的事实源已确认
- Deliverables: 上下文摘要
- Notes: 只依赖官方文档与本仓代码，不靠旧 research 残留猜测

### 2.2 确立 Task 4 执行顺序
- [x] Task: 采用“依赖/设计确认 -> failing test -> runtime types + runtime skeleton -> verify -> commit”顺序
- Goal: 满足 requirement-to-delivery + TDD + git 提交流程
- Done when: 执行顺序稳定
- Deliverables: Task 4 执行顺序
- Notes: 完成后继续推进 Task 5

## Part 3: 当前阶段执行
### 3.1 完成 Task 4 runtime 单入口
- [x] Task: 落地 Deep Agents runtime skeleton、研究模式工具装配约束与后端分层配置
- Goal: 恢复研究模式唯一 runtime 入口
- Done when: `deep_research_runtime.py` / `research_runtime_types.py` 与测试完成，且无旧并行 runtime 残留
- Deliverables: runtime 文件与定向测试
- Notes: 本轮未发现需删除的旧 runtime 文件；当前以 `deep_research_runtime.py` 为唯一 research runtime 入口

### 3.2 完成 Task 4 定向验证
- [x] Task: 新增并通过 Task 4 对应测试
- Goal: 证明单入口、禁用 MCP、后端分层、主/子代理模型与恢复配置真实存在
- Done when: 先红后绿记录完整
- Deliverables: 测试文件与验证输出
- Notes: 已完成红测（缺少 `app.services.deep_research_runtime` 导致收集失败）-> 绿测（`5 passed`）

## Part 4: 验证与切换
### 4.1 验证 Task 4 产物
- [x] Task: 运行 Task 4 定向 pytest / ruff / 依赖检查
- Goal: 为 git 提交提供新鲜证据
- Done when: 验证输出支持“已验证通过”
- Deliverables:
  - `uv run pytest tests/research/test_deep_research_runtime.py -q` -> `5 passed`
  - `uv run pytest tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py -q` -> `18 passed`
  - `uv run ruff check src/app/services/deep_research_runtime.py src/app/services/research_runtime_types.py tests/research/test_deep_research_runtime.py` -> `All checks passed!`
- Notes: 若失败则继续修复

### 4.2 同步状态并提交
- [x] Task: 更新 todo / state，完成 Task 4 git 提交，并锁定下一个任务为 Task 5
- Goal: 保持一次一任务的执行纪律
- Done when: 已提交且下个任务明确
- Deliverables: 提交记录与下一任务决策
- Notes: 未提交前不得声称 Task 4 完成
