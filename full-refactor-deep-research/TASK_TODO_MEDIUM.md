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
- Project Modules: Deep Agents runtime；source-aware tooling；service / event / artifact orchestration；API / worker / export
- Brownfield Context / Codebase Map:
  - Phase 1 已完成并提交：持久化三表、schema、planner
  - Task 4 已完成并提交：`backend/src/app/services/deep_research_runtime.py`、`research_runtime_types.py`
  - Task 5 已完成并提交：`build_research_tool_registry`、`research_tools.py`、`research_source_bundle.py`、`research_finalizer.py`
  - Task 6 已完成并提交：`a12593e feat(research): add research service orchestration`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 在已具备 research session API / worker 后，补齐导出链路对 research artifacts 的单路径读取，避免继续混用旧 run-centric 导出事实源
- Why Now / Decision Driver: 没有 Task 8，Task 13 的 demo / export 验证仍会卡在旧 research 导出路径上
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Phase Goal: 完成 Task 9（前端数据层直接改造当前研究服务）
- Phase Scope:
  - 包含：`frontend/src/services/research.ts`、`frontend/src/types/researchEvents.ts`、`frontend/src/hooks/queries/useResearch.ts`
  - 不包含：Task 10+ research workbench 组件
- Non-goals:
  - 不回退到旧 run-centric research runtime
  - 不在此轮触碰 frontend workbench
- Phase Deliverables:
  - `frontend/src/services/research.ts`
  - `frontend/src/types/researchEvents.ts`
  - `frontend/src/hooks/queries/useResearch.ts`
  - 前端 typecheck 证据
- Active Execution Wave: Task 8 已完成；下一任务 = Task 9 frontend data layer
- Entry Criteria:
  - Phase 1 已完成
  - Task 4 / Task 5 的 runtime 与 source-aware tooling 已通过定向验证
- Exit Criteria / Done Definition:
  - Task 9 代码与测试完成并提交
  - 前端 research service 完全切到 `session_id` 契约
  - 定向 pytest / ruff 通过
- Transition Notes / Next Phase Trigger: Task 9 提交后继续推进 Task 10（research workbench）

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

### 1.2 锁定 Task 9 目标
- [x] Task: 将当前执行波次切换到 `tasks.md` Task 9（frontend data layer）
- Goal: 在已完成 session API 与 export 后，让前端 research service 彻底切到 `session_id` + SSE 事件契约
- Done when: Task 9 边界与验收清晰
- Deliverables: Task 9 执行目标
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

### 2.2 确立 Task 9 执行顺序
- [x] Task: 采用“盘点 frontend 研究服务 -> Task 9 红测 / typecheck -> data layer 改造 -> 绿测 -> 状态同步 -> 提交”顺序
- Goal: 满足 TDD 与一次一任务提交纪律
- Done when: 执行顺序稳定
- Deliverables: Task 9 执行顺序
- Notes: 本次先完成 Task 8 提交，再启动 Task 9

## Part 3: 当前阶段执行
### 3.1 Task 8 红测完成记录
- [x] Task: `backend/tests/research/test_research_exporter.py` 已覆盖 report dual-artifact success / missing artifact / export service queue / worker error mapping
- Goal: 先固定 export / artifact read 契约
- Done when: pytest 因 `research_exporter.py` 缺失而稳定失败后已转绿
- Deliverables: failing test -> passing test
- Notes: 红测已验证 research exporter 缺失时会失败

### 3.2 落地 Task 8 exporter / export worker 集成
- [x] Task: 已实现 `research_exporter.py`、`export_service.py` 与 `worker/tasks/export.py` 改造
- Goal: 让导出链路只按 `session_id` 读取 `report_md` / `report_json`
- Done when: 红测转绿
- Deliverables:
  - `backend/src/app/services/exporters/research_exporter.py`
  - `backend/src/app/services/export_service.py`
  - `backend/src/app/worker/tasks/export.py`
  - `backend/src/app/schemas/exports.py`
  - `backend/tests/research/test_research_exporter.py`
- Notes:
  - `ExportType` 已支持 `research`
  - 缺失关键工件时统一返回 `ARTIFACT_INCOMPLETE`

## Part 4: 验证与切换
### 4.1 验证 Task 8 产物
- [x] Task: 运行 Task 8 定向 pytest / ruff
- Goal: 为下一次提交提供 fresh verification
- Done when: 验证输出支持“已验证通过”
- Deliverables:
  - `uv run pytest tests/research/test_research_exporter.py -q` -> `4 passed`
  - `uv run ruff check src/app/schemas/exports.py src/app/services/export_service.py src/app/services/exporters/research_exporter.py src/app/worker/tasks/export.py tests/research/test_research_exporter.py` -> `All checks passed!`
  - `uv run pytest tests/api/test_research_endpoints.py tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py tests/research/test_research_service.py tests/research/test_research_exporter.py -q` -> `35 passed`
- Notes: 若提交前再有改动，需要重新跑 fresh verification

### 4.2 同步状态并提交
- [x] Task: 更新 todo / state，完成 Task 8 git 提交，并锁定下一个任务为 Task 9
- Goal: 保持执行节奏稳定
- Done when: 已提交且下个任务明确
- Deliverables:
  - Task 8 提交记录：`a8d1a72 feat(research): add research artifact exports`
  - 下一任务锁定为 Task 9（frontend data layer）
- Notes: 下一步先做 Task 9 红测 / typecheck
