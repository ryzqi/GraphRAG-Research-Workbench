# Task Todo - Medium

## Project / Phase Context
- Current Phase: Phase 5 - Re-render Optimization
- Phase Goal: 清理无效 memo/effect/state 订阅，降低不必要重渲染。
- Phase Scope:
  - 包含：5.1、5.2、5.3、5.7、5.10 的真实代码落点
  - 不含：视觉改动、全局状态管理重构
- Phase Deliverables:
  - `KbChatPage.tsx` 渲染期派生状态
  - `ModelConfigPage.tsx` 去除 draft 同步 effect
  - `EvidenceList.tsx` / `KnowledgeBaseSelector.tsx` 移除 primitive `useMemo`
  - 验证与 commit

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将 re-render 优化收敛为“派生状态回到 render + 移除无效 memo/effect”

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认验证策略与 build 提权约束

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 完成 `KbChatPage.tsx`、`ModelConfigPage.tsx`、`EvidenceList.tsx`、`KnowledgeBaseSelector.tsx` 审计

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 5 执行顺序

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 完成 `KbChatPage.tsx` 与 `ModelConfigPage.tsx` 的派生状态收口

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成 primitive `useMemo` 清理与验证

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行 Phase 5 对应验证
- Notes:
  - `npm run typecheck` 通过
  - 定向 `eslint` 通过
  - `npm run build` 通过

### 4.2 Reconcile status and decide transition
- [x] Task: 提交 Phase 5 commit 并准备切到 Phase 6
- Notes: 已提交 `53a8dd2`
