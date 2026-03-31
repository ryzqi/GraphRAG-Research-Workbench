# Task Todo - Fine

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
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/hooks`, `frontend/src/components`, `frontend/src/views`, `frontend/src/theme`
- Brownfield Context / Codebase Map:
  - `frontend/src/hooks/usePrefersReducedMotion.ts`（新增长生命周期共享监听）
  - `frontend/src/hooks/queries/useKbChatGraphSchema.ts`（新增长生命周期 SWR hook）
  - `frontend/src/components/chat/useTypewriterStream.ts`
  - `frontend/src/components/chat/MessageList.tsx`
  - `frontend/src/views/KbChatPage.tsx`
  - `frontend/src/theme/ThemeProvider.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 客户端不应为每条消息单独挂同类监听，也不应在滚动热路径和可共享请求上维持不必要的手写逻辑
- Why Now / Decision Driver: Phase 4 明确要求 client-side data fetching 优化
- Phase Roadmap Summary: 当前仅执行 Phase 4，完成后切换 Phase 5
- Current Phase: Phase 4 - Client-Side Data Fetching
- Current Phase Inputs:
  - Phase 3 commit `7fd0750`
  - `useTypewriterStream.ts` / `MessageList.tsx` / `KbChatPage.tsx` 当前实现
  - `ThemeProvider.tsx` 当前主题模式 localStorage 存储
- Active Execution Wave:
  - 共享 reduced-motion 监听
  - passive scroll listener
  - graph schema 的 SWR 化
- Phase Goal: 让客户端监听与请求路径更轻、更可共享且不改变 UI 表现
- Phase Scope:
  - 包含：4.1、4.2、4.3 的代码落地；4.4 的审计结论
  - 不包含：Phase 5 及之后内容
- Non-goals:
  - 不改动页面 UI、SWR 结果结构与主题行为
  - 不为了覆盖规则而引入低价值 localStorage schema 迁移
- Phase Deliverables:
  - `usePrefersReducedMotion.ts`
  - `useKbChatGraphSchema.ts`
  - `MessageList.tsx` passive scroll listener
  - `KbChatPage.tsx` 的 SWR schema 查询
  - typecheck / eslint / build 证据
- Entry Criteria: Phase 3 已提交并归档
- Phase Exit Criteria:
  - 重复 reduced-motion 监听已共享化
  - MessageList 的 scroll listener 为 passive
  - graph schema 查询交由 SWR 去重
  - 验证完成并提交 commit
- Eval Objective: 降低客户端重复监听与可共享请求的开销
- Evaluation Surface / Baseline:
  - `useTypewriterStream.ts` 每实例单独监听媒体查询
  - `MessageList.tsx` 使用 React `onScroll`
  - `KbChatPage.tsx` 用手写 effect 请求 schema
  - `ThemeProvider.tsx` 仅持有单个轻量主题 token
- Metric / Rubric: 共享监听边界清晰、滚动监听更轻、schema 请求更可复用、验证通过
- Pass Threshold / Stop Condition: Phase 4 所有目标文件完成并通过验证
- Next Phase Trigger / Transition Notes: Phase 4 commit 完成后刷新为 Phase 5
- Previous Phase Summary: Phase 3 已完成并归档

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将 client-side data fetching 收敛为明确可执行的文件级任务
- Goal: 避免把 Phase 4 扩成全局事件系统重构
- Inputs / Dependencies: 目标源码、SWR 基础设施、滚动热路径
- Procedure / Implementation notes: 只处理真实热路径；4.4 无高价值代码落点时如实记录
- Output / Artifact: 可执行目标说明
- Done when: 已明确改动文件与无落点项
- Verification: Medium todo 已同步
- Notes: 4.1/4.2/4.3 为主要代码落点

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出 Phase 4 所需依赖与验证约束
- Goal: 让执行与验证保持一致
- Inputs / Dependencies: typecheck / eslint / build、目标文件
- Procedure / Implementation notes: 保持最小改动，优先复用现有 SWR 与组件结构
- Output / Artifact: 当前阶段依赖清单
- Done when: 提权需求与验证命令明确
- Verification: `PROJECT_EXECUTION_STATE.md` 已同步
- Notes: build 仍需可能提权

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化 client-side data fetching 热点审计结论
- Goal: 对应真实客户端热路径
- Inputs / Dependencies: 目标 hooks / 组件 / 页面
- Procedure / Implementation notes:
  - `useTypewriterStream` 在消息级实例中会重复注册 reduced-motion 监听
  - `MessageList` 的 scroll listener 位于高频滚动路径
  - `KbChatPage` 的 graph schema 请求可交给 SWR 去重
  - 当前 localStorage 只有主题模式一个轻量 token，4.4 暂无高价值改动
- Output / Artifact: Phase 4 上下文图
- Done when: 每个目标项都能映射到具体文件
- Verification: 目标文件已审阅
- Notes: 不扩展到非热点监听与主题偏好迁移

### 2.2 Break the current phase into executable units
- [x] Task: 拆解 Phase 4 执行单元
- Goal: 保持可跟踪
- Inputs / Dependencies: baseline、目标文件
- Procedure / Implementation notes:
  - 新增共享 reduced-motion hook
  - MessageList 改 passive scroll listener
  - graph schema 新增 SWR hook 并接入 KbChatPage
  - 跑 typecheck / eslint / build
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 3.x/4.x 已细化
- Notes: 优先保留现有 UI 与数据结构

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 处理共享监听与 passive scroll 热路径
- Goal: 先消除重复监听并优化滚动热路径
- Inputs / Dependencies:
  - `frontend/src/hooks/usePrefersReducedMotion.ts`
  - `frontend/src/components/chat/useTypewriterStream.ts`
  - `frontend/src/components/chat/MessageList.tsx`
- Procedure / Implementation notes:
  - 用 `useSyncExternalStore` 建立共享 reduced-motion store
  - `useTypewriterStream` 改复用共享 hook
  - `MessageList` 改用 passive scroll listener
- Output / Artifact: 共享监听与滚动热路径改动
- Done when: reduced-motion 监听共享化；scroll listener 为 passive
- Verification: typecheck / eslint / build
- Notes:
  - 已完成 `usePrefersReducedMotion.ts`
  - 已完成 `useTypewriterStream.ts` 接线
  - 已完成 `MessageList.tsx` passive scroll listener

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 完成 graph schema 的 SWR 化、4.4 审计留痕与验证
- Goal: 收口 Phase 4
- Inputs / Dependencies:
  - `frontend/src/hooks/queries/useKbChatGraphSchema.ts`
  - `frontend/src/views/KbChatPage.tsx`
  - typecheck / eslint / build
- Procedure / Implementation notes:
  - graph schema 请求切换到 SWR
  - 移除 KbChatPage 内的手写 effect/fetch
  - 4.4 以审计结论记录，不做低价值 localStorage 改动
- Output / Artifact: SWR 接线、验证结果、commit
- Done when: graph schema 查询交由 SWR；验证完成
- Verification: typecheck / eslint / build
- Notes:
  - 已完成 `useKbChatGraphSchema.ts`
  - 已完成 `KbChatPage.tsx` 接线
  - 当前仅剩 git commit 动作

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与 Phase 4 结论直接相关的验证
- Goal: 防止只改代码不验证 client-side 路径
- Inputs / Dependencies: 完成后的代码、typecheck / eslint / build
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑定向 `eslint`
  - 跑 `npm run build`
- Output / Artifact: Phase 4 验证记录
- Done when: 验证足以支撑 client data fetching 优化结论
- Verification: 命令输出留痕
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/hooks/usePrefersReducedMotion.ts src/hooks/queries/useKbChatGraphSchema.ts src/components/chat/useTypewriterStream.ts src/components/chat/MessageList.tsx src/views/KbChatPage.tsx` 通过
  - `npm run build` 通过（require_escalated）

### 4.2 Reconcile phase completion and prepare the next step
- [ ] Task: 更新状态、提交 Phase 4 commit，并准备切到 Phase 5
- Goal: 留下完整审计轨迹
- Inputs / Dependencies: 已验证改动、git 工作区
- Procedure / Implementation notes:
  - 更新 active planning files
  - 提交明确 commit
  - 归档 Phase 4 计划
- Output / Artifact: commit + 过渡决策
- Done when: Phase 4 commit 完成，Phase 5 入口明确
- Verification: `git log -1 --stat`
- Notes: 当前 planning files 已到完成态；提交当前 commit 后才可标记完成并刷新为 Phase 5
