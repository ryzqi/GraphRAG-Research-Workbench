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
- Project Modules: Deep Agents runtime；source-aware tooling；service / event / artifact orchestration；API / worker / export；frontend data layer / workbench
- Brownfield Context / Codebase Map:
  - Phase 1 已完成并提交：持久化三表、schema、planner
  - Task 4 已完成并提交：`backend/src/app/services/deep_research_runtime.py`、`research_runtime_types.py`
  - Task 5 已完成并提交：`build_research_tool_registry`、`research_tools.py`、`research_source_bundle.py`、`research_finalizer.py`
  - Task 6 已完成并提交：`a12593e feat(research): add research service orchestration`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 在已具备 research session API / worker 后，补齐导出链路对 research artifacts 的单路径读取，避免继续混用旧 run-centric 导出事实源
- Why Now / Decision Driver: 没有 Task 8，Task 13 的 demo / export 验证仍会卡在旧 research 导出路径上
- Current Phase: Phase 4 - 前端研究工作台 hard cut
- Phase Goal: 完成 Task 10（前端事件驱动研究工作台）
- Phase Scope:
  - 包含：`frontend/src/views/ResearchPage.tsx`、timeline / plan preview / interrupt / artifact 面板
  - 不包含：Task 11+ observability gate
- Non-goals:
  - 不回退到旧 run-centric research runtime
  - 不在此轮触碰 Task 11+ 门禁与可观测
- Phase Deliverables:
  - `ResearchTimeline`
  - `PlanPreviewPanel`
  - `InterruptDecisionPanel`
  - `ArtifactPanel`
  - `ResearchPage` workbench 集成
- Active Execution Wave: Task 9 已完成；下一任务 = Task 10 research workbench
- Entry Criteria:
  - Phase 1 已完成
  - Task 4 / Task 5 的 runtime 与 source-aware tooling 已通过定向验证
- Exit Criteria / Done Definition:
  - Task 10 代码与验证完成并提交
  - 当前研究页面可展示计划、timeline、interrupt、artifacts
  - planner -> confirm -> runtime -> interrupt -> resume -> final 主链路可联调
- Transition Notes / Next Phase Trigger: Task 10 提交后继续推进 Task 11（observability / eval / gate）

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

### 1.2 锁定 Task 10 目标
- [x] Task: 将当前执行波次切换到 `tasks.md` Task 10（research workbench）
- Goal: 在已完成 session-based data layer 后，接通计划、timeline、中断与工件面板
- Done when: Task 10 边界与验收清晰
- Deliverables: Task 10 执行目标
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

### 2.2 确立 Task 10 执行顺序
- [x] Task: 采用“盘点当前 ResearchPage / 数据层 -> Task 10 红测或 type-level 基线 -> workbench 组件接线 -> 绿测 -> 状态同步 -> 提交”顺序
- Goal: 满足 TDD 与一次一任务提交纪律
- Done when: 执行顺序稳定
- Deliverables: Task 10 执行顺序
- Notes: 本次先完成 Task 9 提交，再启动 Task 10

## Part 3: 当前阶段执行
### 3.1 Task 9 红测完成记录
- [x] Task: `frontend/src/services/research.test.ts` 与 `frontend/src/services/exports.test.ts` 已覆盖 session endpoint、event merge、续流 header/query、research export `session_id`
- Goal: 先固定 frontend session/event/artifact 契约
- Done when: Vitest 因 `frontend/src/types/researchEvents.ts` 缺失与旧 run-centric service 不满足新契约而失败后已转绿
- Deliverables: failing test -> passing test
- Notes: 红测已验证 research data layer 不能继续依赖旧 `/research/runs*`

### 3.2 落地 Task 9 frontend data layer hard cut
- [x] Task: 已实现 `research.ts`、`researchEvents.ts`、`useResearch.ts`、`ResearchPage.tsx` 与 `exports.ts` 改造
- Goal: 让前端研究服务只使用 `session_id` + `ResearchEventEnvelope` + `ResearchArtifactsResponse`
- Done when: 红测转绿
- Deliverables:
  - `frontend/src/services/research.ts`
  - `frontend/src/types/researchEvents.ts`
  - `frontend/src/hooks/queries/useResearch.ts`
  - `frontend/src/views/ResearchPage.tsx`
  - `frontend/src/services/exports.ts`
- Notes:
  - 统一流消费器按 `event_id` 去重、按 `sequence` 重排
  - 续流优先 `Last-Event-ID`，失败后回退 artifacts 快照 + 增量流
  - 已删除旧 run-centric ResearchPage 沉淀入口

## Part 4: 验证与切换
### 4.1 验证 Task 9 产物
- [x] Task: 运行 Task 9 定向 Vitest / typecheck
- Goal: 为下一次提交提供 fresh verification
- Done when: 验证输出支持“已验证通过”
- Deliverables:
  - `npx vitest run src/services/research.test.ts src/services/exports.test.ts` -> `8 passed`
  - `npx vitest run src/services` -> `78 passed`
  - `npm run typecheck` -> `passed`
- Notes: 若提交前再有改动，需要重新跑 fresh verification

### 4.2 同步状态并提交
- [x] Task: 更新 todo / state，完成 Task 9 git 提交，并锁定下一个任务为 Task 10
- Goal: 保持执行节奏稳定
- Done when: 已提交且下个任务明确
- Deliverables:
  - Task 9 提交记录：`feat(research): cut frontend to session contract`
  - 下一任务锁定为 Task 10（research workbench）
- Notes: 下一步先做 workbench 组件边界盘点与红测基线
