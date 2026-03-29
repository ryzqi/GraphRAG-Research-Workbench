# Project Phase Roadmap

## Project Context
- Project Name: full-refactor-deep-research
- Project Mode: Multi-phase
- Execution State File / Reference: `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示与交付使用者
- Customer Problem / Desired Outcome: 恢复并重构深度研究主路径，使其以 `session_id` 为唯一业务事实源、以最新 Deep Agents 作为唯一 runtime harness，并最终可在当前前后端中稳定启动、执行、恢复与导出。
- Why Now / Decision Driver: 旧 research backend 已在迁移 `a6b8c9d0e1f2_remove_research_stack.py` 中整体移除，而前端仍保留 run-centric 调用；继续堆兼容层会扩大债务，必须按单路径重建。
- Overall Goal: 按 `full-refactor-deep-research/tasks.md` 落地当前研究单路径：`create session -> preflight planner -> confirm -> runtime -> finalizer -> artifacts`。
- Current Active Phase: Phase 5 - 可观测、文档同步与最终交付门禁
- Overall Success Criteria:
  - 后端恢复 `research_sessions / research_events / research_artifacts` 三表，且迁移、模型、测试一致。
  - 研究运行时只保留 `create_deep_agent` 单入口，不保留旧 research engine / run-centric 兼容路径。
  - 当前公开 API、Worker、导出链路与前端研究工作台统一切到 `session_id` 契约。
  - 完成完整验证：后端测试、前端类型/构建、demo 脚本、实际启动检查全部通过。
- Non-goals:
  - 不保留旧 `/api/v1/research/runs*` 兼容接口。
  - 不保留旧 research `AgentRunType` 或双轨 research runtime。
  - 不在本项目内继续演化“普通聊天 research tool”作为深度研究替代实现。
- Artifact Policy / Active Planning Files:
  - `full-refactor-deep-research/PROJECT_PHASE_ROADMAP.md`
  - `full-refactor-deep-research/TASK_TODO_MEDIUM.md`
  - `full-refactor-deep-research/TASK_TODO_FINE.md`
  - `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Key Constraints:
  - 必须以 2026-03-29 当日最新官方 Deep Agents 文档为事实源校准用法。
  - 一次只完成一个任务，任务完成后立即验证并 git 提交。
  - 若发现旧 research 遗留实现，直接删除，不保留兼容胶水。
  - 最终必须跑测试与启动验证；失败则继续修复，直到通过。
- Key Risks / Unknowns:
  - 当前 backend 依赖中尚未声明 `deepagents` 包，Phase 2 需结合最新官方发布状态决定稳定版本/预发布版本。
  - 研究后端当前被整体移除，恢复时需避免重新耦合到旧 `agent_runs` 模型。
  - Deep Agents 官方文档与 PyPI发布节奏存在 stable / pre-release 分叉，需在进入 runtime 阶段前锁定版本策略。
- Parked / Deferred Threads:
  - Deep Agents 版本最终锁定与依赖升级，放到进入 runtime phase 时一起提交。
  - 前端 timeline 视觉细化放到 frontend/workbench phase，不在基础底座阶段展开。
- Last Updated: 2026-03-30

## Module Map
- Module / Domain 1: 后端研究域模型与持久化
  - Responsibility: 三表模型、Alembic 迁移、事件/工件幂等约束、状态机边界
  - Key dependencies: `backend/src/app/models/*`, `backend/src/app/db/base.py`, `backend/alembic/versions/*`
  - Notes: 当前研究表已被移除，需从干净基线重建
- Module / Domain 2: 契约与会话编排
  - Responsibility: `schemas/research.py`、planner/runtime/finalizer 服务、interrupt/resume 语义
  - Key dependencies: `backend/src/app/schemas`, `backend/src/app/services`, `backend/src/app/worker/tasks`
  - Notes: 必须以 `session_id` 而非旧 `run_id` 为主键
- Module / Domain 3: Deep Agents runtime 与 source-aware tooling
  - Responsibility: `create_deep_agent` 单入口、subagents、backends、四类 provider、finalizer
  - Key dependencies: Deep Agents 官方文档、依赖版本、工具注册层、SearXNG/Tavily/Jina/arXiv 工具
  - Notes: 必须删除旧 runtime 残留，不保留并行 research 引擎
- Module / Domain 4: 当前 API / SSE / 导出与前端研究工作台
  - Responsibility: 当前公开研究接口、SSE、artifact 读取、前端会话服务与工作台 UI
  - Key dependencies: `backend/src/app/api/v1`, `frontend/src/services/research.ts`, `frontend/src/hooks`, `frontend/src/components`
  - Notes: 前端目前仍是旧 `/runs` 语义，需要 hard cut
- Module / Domain 5: 可观测、评测、启动与交付门禁
  - Responsibility: tracing、故障注入、门禁、demo 脚本、测试与启动验证
  - Key dependencies: `backend/tests`, `frontend` build/typecheck, `scripts/demo_research.ps1`, `scripts/start_all.ps1`
  - Notes: 项目级完成判断集中在本模块

## Phase Roadmap
### Phase 1: 研究域模型与契约底座
- Status: Completed
- Objective: 先恢复三表模型、会话状态机、事件/工件唯一约束，并补齐研究契约与基础 planner。
- Scope Boundary: 覆盖 `tasks.md` 的 Task 1-3；不进入 Deep Agents runtime、API 集成与前端改造。
- Modules Involved: 后端研究域模型与持久化；契约与会话编排
- Main Deliverables: 三表 ORM、Alembic 迁移、研究 schema、preflight planner、对应测试
- Entry Conditions: 当前仓库处于 research backend 被移除后的干净基线；最新官方 Deep Agents 文档已核对
- Completion Conditions: Task 1-3 完成并提交，基础测试通过，可为 runtime phase 提供稳定业务壳层
- Transition Notes: 完成后进入 Phase 2，并在进入前锁定 `deepagents` 依赖策略

### Phase 2: Deep Agents 单引擎运行时与来源路由
- Status: Completed
- Objective: 按最新官方 Deep Agents 用法接入统一 runtime、source-aware tools/subagents 与 finalizer。
- Scope Boundary: 覆盖 `tasks.md` 的 Task 4-6；不改当前 API / 前端。
- Modules Involved: Deep Agents runtime 与 source-aware tooling；契约与会话编排
- Main Deliverables: `deep_research_runtime.py`、runtime types、source routing、artifact/event stores、ResearchService
- Entry Conditions: Phase 1 完成；三表与 planner 契约稳定
- Completion Conditions: runtime 单入口、四类 provider、service orchestration 与测试完成
- Transition Notes: 进入 Phase 3 前删除旧 research 调用路径

### Phase 3: 当前 API / SSE / 导出集成
- Status: Completed
- Objective: 把当前公开研究接口、Worker 与导出链路切到新 session-driven 契约。
- Scope Boundary: 覆盖 `tasks.md` 的 Task 7-8；不做前端工作台视觉细化。
- Modules Involved: 当前 API / SSE / 导出与前端研究工作台（数据层部分）
- Main Deliverables: `/api/v1/research/sessions*` 接口、统一 SSE 映射、export 改造、相关测试
- Entry Conditions: Phase 2 完成；ResearchService 可跑通 planner/runtime/finalizer
- Completion Conditions: 当前 API/worker/export 全切换完成，旧 run-centric backend 彻底删除
- Transition Notes: 进入 Phase 4 时前端数据层可直接接入新协议

### Phase 4: 前端研究工作台 hard cut
- Status: Completed
- Objective: 让当前前端研究服务与工作台完全使用 session/event/artifact 契约。
- Scope Boundary: 覆盖 `tasks.md` 的 Task 9-10；不做 observability gate。
- Modules Involved: 前端研究数据层与工作台
- Main Deliverables: 新事件类型、hooks、timeline / plan preview / interrupt / artifact 面板、联调验收
- Entry Conditions: Phase 3 完成；后端接口稳定
- Completion Conditions: 当前研究页面可完成 planner -> confirm -> runtime -> interrupt -> resume -> final 主链路
- Transition Notes: 进入 Phase 5 执行门禁、文档同步与最终启动

### Phase 5: 可观测、文档同步与最终交付门禁
- Status: Active
- Objective: 补齐 tracing / gate / docs / demo 脚本，并完成全量测试与启动验证。
- Scope Boundary: 覆盖 `tasks.md` 的 Task 11-13。
- Modules Involved: 可观测、评测、启动与交付门禁；文档同步
- Main Deliverables: observability/eval、文档同步、demo 脚本、最终测试与启动通过记录
- Entry Conditions: Phase 4 完成；主链路已联通
- Completion Conditions: 全量验证通过，可作为当前研究单路径发布基线
- Transition Notes: 项目完成

## Phase History / Change Log
- 2026-03-30 / Phase 4 完成，切换到 Phase 5
  - What changed: Task 10 前端 workbench 已完成并提交；Task 11 已落地 trace / metrics / gate、故障注入、事件回放、rollback drill 与 interrupt-resume E2E。
  - Why it changed: 当前 research 主链路已同时具备页面工作台与最小可观测门禁，可以进入文档同步与最终交付收口。
  - Impact on current or future phases: 当前 active todo 切到 Task 12，下一步是文档 / 契约同步，随后进入 Task 13 全量测试、build 与启动验证。
- 2026-03-30 / Phase 3 完成，切换到 Phase 4
  - What changed: Task 7-8 当前 research API / worker / export 已全部提交，Task 9 已将 frontend research service / hooks / page 切到 session/event/artifact 契约。
  - Why it changed: 前端已具备接入当前研究会话协议的最小数据层，可以开始 workbench hard cut。
  - Impact on current or future phases: Phase 4 将继续完成 timeline / plan preview / interrupt / artifact panels，并联调主链路。
- 2026-03-30 / Phase 2 完成，切换到 Phase 3
  - What changed: Task 4-6 runtime、source-aware tooling 与 service orchestration 已完成并提交。
  - Why it changed: 当前业务壳层已能稳定支撑 current API / export 接入。
  - Impact on current or future phases: Phase 3 以当前 session-driven 公开端点为唯一事实源推进 API / export / frontend data layer。
- 2026-03-29 / Phase 1 完成，切换到 Phase 2
  - What changed: Task 1-3 已完成并分别提交；已归档 Phase 1 medium/fine todo，准备刷新 Phase 2 active planning files
  - Why it changed: 三表、schema、planner 基础壳层已就绪，可以进入 runtime / source routing 实现
  - Impact on current or future phases: Phase 2 将先解决 `deepagents` 依赖与 runtime 单入口问题，再继续 service / API 集成
- 2026-03-29 / 初始化 roadmap
  - What changed: 将 `tasks.md` 重排为 5 个可连续执行阶段，并锁定 Phase 1 为当前 active phase
  - Why it changed: 用户要求一次只完成一个任务并逐任务提交，需要稳定的多阶段执行外壳
  - Impact on current or future phases: 所有后续切换都将以该 roadmap 为项目级唯一事实源

## Archive References
- Phase archive path(s): `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-1-foundation.md`, `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-1-foundation.md`, `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-4-frontend-workbench.md`, `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-4-frontend-workbench.md`
- Notes about where historical phase todos, state snapshots, or verification artifacts were stored: phase 切换时归档旧 medium/fine todo，execution state 持续覆盖最新状态；Task 11 rollback drill 记录位于 `full-refactor-deep-research/research-rollback-drill-record.md`
