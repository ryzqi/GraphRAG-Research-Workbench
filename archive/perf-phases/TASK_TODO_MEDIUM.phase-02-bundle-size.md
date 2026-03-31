# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-01-waterfalls.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-01-waterfalls.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-01-waterfalls.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/theme`, `frontend/src/views`, `frontend/src/components/research`, `frontend/src/components/shell`
- Brownfield Context / Codebase Map:
  - `frontend/src/theme/ThemeProvider.tsx`
  - `frontend/src/theme/index.ts`
  - `frontend/src/views/ResearchPage.tsx`
  - `frontend/src/components/research/ArtifactPanel.tsx`
  - `frontend/src/components/research/ResearchAdvancedEventsPanel.tsx`
  - `frontend/src/components/shell/GeminiShell.tsx`
  - `frontend/.next/analyze/client.html`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 减少前端初始 bundle 中不必要的模块，延后非关键研究面板与大依赖加载，并消除本地 barrel import。
- Why Now / Decision Driver: Phase 1 已提交，按用户要求切入 Phase 2 - Bundle Size Optimization。
- Phase Roadmap Summary: 当前阶段完成后，进入 Phase 3 - Server-Side Performance。
- Current Phase: Phase 2 - Bundle Size Optimization
- Phase Goal: 依据 analyzer 与代码审计，处理当前最明确的 bundle 反模式。
- Phase Scope:
  - 包含：2.1、2.2、2.3、2.4、2.5
  - 不含：服务端缓存、重渲染、视觉改造
- Non-goals:
  - 不重写研究页结构
  - 不改动现有 UI 风格
- Phase Deliverables:
  - 消除 `src/theme` 本地 barrel import
  - 研究页重面板改为按需动态加载
  - 非关键 markdown / advanced events 相关依赖后移
  - Sidebar 基于用户意图预加载
  - analyzer / build / typecheck 验证与 commit
- Active Execution Wave: 代码审计结论固化 -> 实施按需加载改造 -> analyzer 验证 -> commit
- Entry Criteria: Phase 1 commit 已完成；Phase 1 todo 已归档
- Exit Criteria / Done Definition:
  - 本地 barrel import 已消除
  - 非关键研究面板和其依赖不再直接压入初始研究页 bundle
  - 已落地至少一处 user-intent preload
  - 验证完成并提交 Phase 2 commit
- Eval Objective: 缩小初始 bundle 负担并将非关键模块后移
- Evaluation Surface / Baseline:
  - `npm run analyze`（baseline 已获取）
  - `client.html` 中 research route 初始包含 Accordion 相关 chunk
  - 代码中 `ThemeProvider.tsx -> ./index` 本地 barrel import
  - `ResearchPage.tsx` 静态导入 `ArtifactPanel` / `ResearchAdvancedEventsPanel`
- Metric / Rubric:
  - 静态 import 改为 dynamic / conditional load
  - 研究路由非关键面板延后
  - 分析构建与类型检查通过
- Pass Threshold / Stop Condition: 所有 Phase 2 范围项完成并拿到 fresh verification
- Transition Notes / Next Phase Trigger: Phase 2 commit 完成后切换到 Phase 3
- Previous Phase Summary: Phase 1 已消除 route prefetch waterfalls，并完成 commit `8e7e152`

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将 bundle 优化收敛为“本地 barrel import + 研究页非关键重模块后移 + Sidebar 意图预加载”
- Goal: 避免把 Phase 2 扩成全局重构
- Done when: 目标文件、目标规则、完成判据明确
- Deliverables: Phase 2 可执行目标
- Notes: 以 analyzer 与代码审计结果为准

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认 analyzer / build 仍需要提权，其他改动保持最小范围
- Goal: 执行时不偏离验证边界
- Done when: 当前阶段验证策略明确
- Deliverables: 验证策略与环境约束
- Notes: `npm run analyze` / `npm run build` 继续按需提权

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 基于 `client.html` 与目标文件完成 bundle 热点审计
- Goal: 只改真实 bundle 热点
- Done when: 已确认 theme barrel、研究页重面板、Sidebar preload 为当前最直接切入点
- Deliverables: 当前阶段上下文结论
- Notes: research route baseline 暴露 Accordion 相关 chunk；`ArtifactPanel` 直接持有 markdown 依赖

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 2 执行顺序
- Goal: 保持最小改动并覆盖 2.1~2.5
- Done when: 执行顺序清晰
- Deliverables: 当前阶段执行计划
- Notes: 先改 import 边界，再改研究页动态加载，最后补 Sidebar preload 与 analyzer 验证

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 消除本地 barrel import，并建立研究页的动态加载边界
- Goal: 先完成最直接的 bundle 入口优化
- Done when: `ThemeProvider` 直接导入具体主题文件；研究页重面板改为按需动态 import
- Deliverables: 主题文件重命名/直连，研究页 dynamic imports
- Notes: 已完成：`ThemeProvider.tsx -> ./md3Theme`；`ArtifactPanel` / `ResearchAdvancedEventsPanel` / `InterruptDecisionPanel` 已切到 dynamic import

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成条件加载、第三方后移、Sidebar preload、验证与 commit
- Goal: 让 Phase 2 真正闭环
- Done when: 所有计划项完成，验证通过，git commit 完成
- Deliverables: bundle 优化改动、验证结果、commit
- Notes: 代码与验证已完成；当前待执行 git commit

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与 Phase 2 结论直接相关的验证
- Goal: 只有在拿到 analyzer / build / typecheck 证据后才完成本阶段
- Done when: 类型检查、构建、analyze 结果支持 bundle 优化结论
- Deliverables: 验证摘要
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/theme/ThemeProvider.tsx src/theme/md3Theme.ts src/components/research/ArtifactPanel.tsx src/components/shell/GeminiShell.tsx src/views/ResearchPage.tsx` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）
  - `npm run analyze` 通过（require_escalated；sandbox 内 `spawn EPERM`）
  - `client.html` 显示 `ArtifactPanel.tsx` / `ResearchAdvancedEventsPanel.tsx` / `InterruptDecisionPanel.tsx` 为独立非初始 chunk

### 4.2 Reconcile status and decide transition
- [x] Task: 更新状态、归档 Phase 2 计划、提交 commit，并决定是否切换到 Phase 3
- Goal: 保留清晰审计轨迹
- Done when: Medium/Fine 状态同步、commit 完成、Phase 3 入口明确
- Deliverables: 阶段总结、归档引用、transition 决策
- Notes: 已完成 commit `7f5eee0`，并已归档当前阶段 planning files；下一步切换到 Phase 3

