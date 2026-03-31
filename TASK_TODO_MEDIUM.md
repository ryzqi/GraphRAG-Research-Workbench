# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-01-waterfalls.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-01-waterfalls.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-01-waterfalls.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-02-bundle-size.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-02-bundle-size.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-02-bundle-size.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-03-server-side.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-03-server-side.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-03-server-side.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/hooks`, `frontend/src/components`, `frontend/src/views`, `frontend/src/theme`
- Brownfield Context / Codebase Map:
  - `frontend/src/hooks/usePrefersReducedMotion.ts`
  - `frontend/src/hooks/queries/useKbChatGraphSchema.ts`
  - `frontend/src/components/chat/useTypewriterStream.ts`
  - `frontend/src/components/chat/MessageList.tsx`
  - `frontend/src/views/KbChatPage.tsx`
  - `frontend/src/theme/ThemeProvider.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 减少客户端重复事件监听与手写数据请求逻辑，让滚动热路径更轻，并在确认无高价值热点时避免无意义 localStorage 改动。
- Why Now / Decision Driver: Phase 3 已提交，按用户要求切入 Phase 4 - Client-Side Data Fetching。
- Phase Roadmap Summary: 当前阶段完成后，进入 Phase 5 - Re-render Optimization。
- Current Phase: Phase 4 - Client-Side Data Fetching
- Phase Goal: 依据前端运行时热路径，收敛重复监听、滚动监听与可共享的客户端数据请求。
- Phase Scope:
  - 包含：4.1、4.2、4.3 的代码落地；4.4 做审计结论
  - 不含：重渲染逻辑重构、视觉改造、主题行为改版
- Non-goals:
  - 不改变页面布局与交互语义
  - 不为了覆盖规则而重写主题偏好存储
- Phase Deliverables:
  - 共享 reduced-motion 监听 hook
  - passive MessageList scroll listener
  - SWR 化的 graph schema 查询
  - 验证与 commit
- Active Execution Wave: 监听去重 -> passive scroll -> SWR graph schema -> 验证 -> commit
- Entry Criteria: Phase 3 commit `7fd0750` 已完成；Phase 3 planning files 已归档
- Exit Criteria / Done Definition:
  - 重复 reduced-motion 监听已收敛到共享 hook
  - MessageList 的滚动监听为 passive
  - KbChat graph schema 请求切到 SWR
  - 验证完成并提交 Phase 4 commit
- Eval Objective: 缩短客户端热路径监听与重复请求开销
- Evaluation Surface / Baseline:
  - `useTypewriterStream.ts` 当前每实例单独监听媒体查询
  - `MessageList.tsx` 当前使用 React `onScroll`
  - `KbChatPage.tsx` 当前手写 effect 请求 schema
  - `ThemeProvider.tsx` 当前 localStorage 仅有单个轻量 token
- Metric / Rubric:
  - 共享监听边界清晰
  - scroll listener 更轻
  - schema 请求交由 SWR 去重
  - 类型检查、定向 lint、构建通过
- Pass Threshold / Stop Condition: 所有 Phase 4 范围项完成并拿到 fresh verification
- Transition Notes / Next Phase Trigger: Phase 4 commit 完成后切换到 Phase 5
- Previous Phase Summary: Phase 3 已完成 server-side performance，并提交 `7fd0750`

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将客户端数据获取优化收敛为“共享监听 + passive scroll + SWR graph schema”
- Goal: 避免把 Phase 4 扩成广泛的事件系统重构
- Done when: 目标文件、目标规则与无落点项明确
- Deliverables: Phase 4 可执行目标
- Notes: 4.4 以审计结论处理，不强行引入偏好存储变更

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认验证策略与沙箱限制
- Goal: 避免把 build 限制误判为代码问题
- Done when: typecheck / eslint / build 的执行策略明确
- Deliverables: 验证策略与环境约束
- Notes: build 在默认沙箱内会触发 `spawn EPERM`，需按需提权

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 基于热点组件与 hooks 完成 client data fetching 审计
- Goal: 只改真实热路径
- Done when: 已定位 reduced-motion 监听、MessageList scroll、graph schema 手写请求与 4.4 的无落点结论
- Deliverables: 当前阶段上下文结论
- Notes: 当前 localStorage 仅主题模式一个轻量 token，不构成高价值热点

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 4 执行顺序
- Goal: 最小改动覆盖监听、滚动与 SWR 去重
- Done when: 执行顺序清晰
- Deliverables: 当前阶段执行计划
- Notes: 先做共享监听，再改 scroll listener，最后替换 schema 请求

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 完成共享 reduced-motion 监听与 passive scroll 落地
- Goal: 先消除热路径中的重复监听与滚动主线程负担
- Done when: 新增共享 hook，MessageList 使用 passive scroll listener
- Deliverables: `usePrefersReducedMotion.ts`、`useTypewriterStream.ts`、`MessageList.tsx`
- Notes: 已完成运行时监听收敛与 scroll listener 切换

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成 graph schema 的 SWR 化、4.4 审计留痕与验证
- Goal: 让 Phase 4 真正闭环
- Done when: `KbChatPage.tsx` 移除手写 effect/fetch，验证通过，commit 待执行
- Deliverables: `useKbChatGraphSchema.ts`、`KbChatPage.tsx`、验证结果、commit
- Notes: 4.4 当前以审计结论处理；当前仅待执行 git commit

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与 Phase 4 结论直接相关的验证
- Goal: 只有在拿到 typecheck / lint / build 证据后才完成本阶段
- Done when: 验证结果支持 client data fetching 优化结论
- Deliverables: 验证摘要
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/hooks/usePrefersReducedMotion.ts src/hooks/queries/useKbChatGraphSchema.ts src/components/chat/useTypewriterStream.ts src/components/chat/MessageList.tsx src/views/KbChatPage.tsx` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile status and decide transition
- [ ] Task: 更新状态、归档 Phase 4 计划、提交 commit，并决定是否切换到 Phase 5
- Goal: 保留清晰审计轨迹
- Done when: Medium/Fine 状态同步、commit 完成、Phase 5 入口明确
- Deliverables: 阶段总结、归档引用、transition 决策
- Notes: 当前 planning files 已更新为 Phase 4 完成态；提交当前 commit 后才可标记完成并刷新到 Phase 5
