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
- Project Modules: Deep Agents runtime；source-aware tooling；service / event / artifact orchestration
- Brownfield Context / Codebase Map:
  - Phase 1 已完成并提交：持久化三表、schema、planner
  - Task 4 已完成并提交：`backend/src/app/services/deep_research_runtime.py`、`research_runtime_types.py`
  - Task 5 已完成并待本次提交：`build_research_tool_registry`、`research_tools.py`、`research_source_bundle.py`、`research_finalizer.py`
  - 当前尚未落地：`ResearchEventStore`、`ResearchArtifactStore`、`ResearchService`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 在已具备 planner、runtime、source bundle、finalizer 骨架后，补齐真正把会话、事件、工件串起来的服务层
- Why Now / Decision Driver: 没有 Task 6，Task 7 的 API / SSE / resume 仍然无法建立在真实 orchestration 之上
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Phase Goal: 完成 Task 6（研究会话编排与持久化服务）
- Phase Scope:
  - 包含：event store、artifact store、ResearchService、状态迁移、幂等恢复测试
  - 不包含：Task 7+ API / worker / frontend
- Non-goals:
  - 不回退到旧 run-centric research runtime
  - 不在此轮接通当前 API 路由与 SSE
- Phase Deliverables:
  - `backend/src/app/services/research_event_store.py`（或等价）
  - `backend/src/app/services/research_artifact_store.py`（或等价）
  - `backend/src/app/services/research_service.py`
  - `backend/tests/research/test_research_service.py`
- Active Execution Wave: Task 5 已完成；下一任务 = Task 6 service/persistence orchestration
- Entry Criteria:
  - Phase 1 已完成
  - Task 4 / Task 5 的 runtime 与 source-aware tooling 已通过定向验证
- Exit Criteria / Done Definition:
  - Task 6 代码与测试完成并提交
  - 能串起 planner -> runtime -> finalizer 的服务层骨架
  - 定向 pytest / ruff 通过
- Transition Notes / Next Phase Trigger: Task 6 提交后继续推进 Task 7（API / stream integration）

## Part 1: 当前阶段需求与范围
### 1.1 完成 Task 5 收口
- [x] Task: 落地 provider-specific research tools、source bundle 与 finalizer
- Goal: 把 runtime 从“只有单入口”推进到“具备 source-aware 基础能力”
- Done when: research tool registry / subagents / finalizer / source bundle 已验证
- Deliverables:
  - `backend/src/app/agents/tools/research_tools.py`
  - `backend/src/app/services/research_source_bundle.py`
  - `backend/src/app/services/research_finalizer.py`
  - `backend/tests/research/test_research_source_tooling.py`
- Notes: Task 5 已完成并将在本次与 planning/state 一起提交

### 1.2 锁定 Task 6 目标
- [ ] Task: 将 `tasks.md` Task 6 收敛为 event store + artifact store + ResearchService + 定向测试
- Goal: 避免在服务层阶段提前把 API / worker / SSE 一并拉进来
- Done when: Task 6 边界与验收清晰
- Deliverables: Task 6 执行目标
- Notes: 当前 phase 仍保持“一次只完成一个任务”

## Part 2: 当前阶段研究与计划
### 2.1 复核 Task 6 依赖上下文
- [ ] Task: 审查 `research_session / research_event / research_artifact` 模型、planner、runtime、finalizer 与现有 DB/service 习惯
- Goal: 让服务层实现贴合当前仓库模式
- Done when: store/service 的职责边界明确
- Deliverables: Task 6 上下文摘要
- Notes: 只基于当前代码与已验证 stop point，不靠旧 research 方案猜测

### 2.2 确立 Task 6 执行顺序
- [ ] Task: 采用“红测 -> event/artifact store -> ResearchService -> 绿测 -> 状态同步 -> 提交”顺序
- Goal: 满足 TDD 与一次一任务提交纪律
- Done when: 执行顺序稳定
- Deliverables: Task 6 执行顺序
- Notes: Task 6 完成后再进入 Task 7

## Part 3: 当前阶段执行
### 3.1 启动 Task 6 红测
- [ ] Task: 新建 `backend/tests/research/test_research_service.py`
- Goal: 先固定 planner -> runtime -> finalizer -> artifacts 的服务层合同
- Done when: pytest 因缺失服务层实现而稳定失败
- Deliverables: failing test
- Notes: 红测需覆盖事件顺序、工件写入、幂等恢复骨架

### 3.2 落地 Task 6 服务层骨架
- [ ] Task: 实现 event store、artifact store、ResearchService
- Goal: 把现有 planner/runtime/finalizer 接成单一路径
- Done when: 红测转绿
- Deliverables: service/store 文件
- Notes: 发现旧 research service 遗留则直接删

## Part 4: 验证与切换
### 4.1 验证 Task 6 产物
- [ ] Task: 运行 Task 6 定向 pytest / ruff
- Goal: 为下一次提交提供 fresh verification
- Done when: 验证输出支持“已验证通过”
- Deliverables: 验证记录
- Notes: 若失败则继续修复

### 4.2 同步状态并提交
- [ ] Task: 更新 todo / state，完成 Task 6 git 提交，并锁定下一个任务为 Task 7
- Goal: 保持执行节奏稳定
- Done when: 已提交且下个任务明确
- Deliverables: 提交记录与下一任务决策
- Notes: 未提交前不得宣称 Task 6 完成
