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
  - Task 5 已完成并提交：`build_research_tool_registry`、`research_tools.py`、`research_source_bundle.py`、`research_finalizer.py`
  - Task 6 已完成并待本次提交：`ResearchEventStore`、`ResearchArtifactStore`、`ResearchService`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 在已具备 planner、runtime、source bundle、finalizer 骨架后，补齐真正把会话、事件、工件串起来的服务层
- Why Now / Decision Driver: 没有 Task 6，Task 7 的 API / SSE / resume 仍然无法建立在真实 orchestration 之上
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Phase Goal: 完成 Task 7（当前端点集合与 Worker 集成）
- Phase Scope:
  - 包含：当前 research API router、service 接线、worker 调用、SSE/interrupt/resume HTTP 契约
  - 不包含：Task 8+ exporter / frontend
- Non-goals:
  - 不回退到旧 run-centric research runtime
  - 不在此轮触碰 frontend workbench
- Phase Deliverables:
  - `backend/src/app/api/v1/endpoints/research.py`
  - `backend/src/app/api/v1/api.py`
  - `backend/src/app/worker/tasks/research.py`
  - `backend/tests/api/test_research_endpoints.py`
- Active Execution Wave: Task 6 已完成；下一任务 = Task 7 endpoint/worker integration
- Entry Criteria:
  - Phase 1 已完成
  - Task 4 / Task 5 的 runtime 与 source-aware tooling 已通过定向验证
- Exit Criteria / Done Definition:
  - Task 7 代码与测试完成并提交
  - `/api/v1/research/*` 当前端点集合可用
  - 定向 pytest / ruff 通过
- Transition Notes / Next Phase Trigger: Task 7 提交后继续推进 Task 8（export / artifact read）

## Part 1: 当前阶段需求与范围
### 1.1 Task 5 / Task 6 收口结果
- [x] Task: 落地 provider-specific research tools、source bundle 与 finalizer
- Goal: 把 runtime 从“只有单入口”推进到“具备 source-aware 基础能力”
- Done when: research tool registry / subagents / finalizer / source bundle 已验证
- Deliverables:
  - `backend/src/app/agents/tools/research_tools.py`
  - `backend/src/app/services/research_source_bundle.py`
  - `backend/src/app/services/research_finalizer.py`
  - `backend/tests/research/test_research_source_tooling.py`
- Notes:
  - Task 5 已完成并提交：`dfbf457 feat(research): add source-aware research tooling`
  - 已补齐 `ResearchEventStore` / `ResearchArtifactStore` / `ResearchService`
  - 已新增 `research_brief`、`interim_findings` 工件与 plan confirm / interrupt / resume 服务接口

### 1.2 锁定 Task 7 目标
- [x] Task: 将当前执行波次切换到 `tasks.md` Task 7（research API / worker / SSE HTTP 契约）
- Goal: 在已完成服务层后，只把当前接口与 worker 接到单一路径 research service 上
- Done when: Task 7 边界与验收清晰
- Deliverables: Task 7 执行目标
- Notes: 继续保持“一次只完成一个任务”

## Part 2: 当前阶段研究与计划
### 2.1 记录 Task 6 已验证结论
- [x] Task: 审查 `research_session / research_event / research_artifact` 模型、planner、runtime、finalizer 与服务层实现的匹配关系
- Goal: 确认 Task 6 真正完成而不是停留在 skeleton
- Done when: store/service 的职责边界明确
- Deliverables: Task 6 上下文摘要
- Notes:
  - `create_session` 已写入 `plan_snapshot` + `research_brief`
  - `execute_session` 已写入 `source_bundle` + `interim_findings` + `interim_summary` + `coverage_gaps` + final reports
  - `confirm_plan` / `interrupt_session` / `resume_session` 已接到事件存储

### 2.2 确立 Task 7 执行顺序
- [x] Task: 采用“定位当前路由/worker -> Task 7 红测 -> research router / worker 改造 -> 绿测 -> 状态同步 -> 提交”顺序
- Goal: 满足 TDD 与一次一任务提交纪律
- Done when: 执行顺序稳定
- Deliverables: Task 7 执行顺序
- Notes: 本次先完成 Task 6 提交，再启动 Task 7

## Part 3: 当前阶段执行
### 3.1 Task 6 红测完成记录
- [x] Task: `backend/tests/research/test_research_service.py` 已覆盖 create / execute / event-idempotency / confirm / interrupt / resume
- Goal: 先固定 planner -> runtime -> finalizer -> artifacts 的服务层合同
- Done when: pytest 因缺失服务层实现稳定失败后已转绿
- Deliverables: failing test -> passing test
- Notes: 红测已验证缺失 `ResearchService` / confirm / interrupt / resume / event_id 幂等时会失败

### 3.2 落地 Task 6 服务层
- [x] Task: 已实现 event store、artifact store、ResearchService
- Goal: 把现有 planner/runtime/finalizer 接成单一路径
- Done when: 红测转绿
- Deliverables:
  - `backend/src/app/services/research_event_store.py`
  - `backend/src/app/services/research_artifact_store.py`
  - `backend/src/app/services/research_service.py`
  - `backend/tests/research/test_research_service.py`
- Notes: 本轮未发现需删除的旧 research service 源文件

## Part 4: 验证与切换
### 4.1 验证 Task 6 产物
- [x] Task: 运行 Task 6 定向 pytest / ruff
- Goal: 为下一次提交提供 fresh verification
- Done when: 验证输出支持“已验证通过”
- Deliverables:
  - `uv run pytest tests/research/test_research_service.py -q` -> `5 passed`
  - `uv run ruff check src/app/services/research_event_store.py src/app/services/research_artifact_store.py src/app/services/research_service.py tests/research/test_research_service.py` -> `All checks passed!`
  - `uv run pytest tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py tests/research/test_research_service.py -q` -> `28 passed`
- Notes: 若提交前再有改动，需要重新跑 fresh verification

### 4.2 同步状态并提交
- [ ] Task: 更新 todo / state，完成 Task 6 git 提交，并锁定下一个任务为 Task 7
- Goal: 保持执行节奏稳定
- Done when: 已提交且下个任务明确
- Deliverables: 提交记录与下一任务决策
- Notes: 未提交前不得宣称 Task 6 完成
