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
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-04-client-data.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-04-client-data.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-04-client-data.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-05-rerender.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-05-rerender.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-05-rerender.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-06-rendering.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-06-rendering.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-06-rendering.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-07-javascript.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-07-javascript.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-07-javascript.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/hooks`
- Brownfield Context / Codebase Map:
  - `frontend/src/hooks/useModalAccessibility.ts`
  - `frontend/src/hooks/useGeneralChatController.ts`
  - `frontend/src/hooks/useKbChatSessionController.ts`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 高频渲染与 DOM 事件 effect 不应持续触发可避免的对象初始化或监听回调重建。
- Why Now / Decision Driver: Phase 7 已提交，按用户要求切入 Phase 8 - Advanced Patterns。
- Phase Roadmap Summary: 当前阶段完成后进入最终全链路验证与收尾。
- Current Phase: Phase 8 - Advanced Patterns
- Phase Goal: 用高级模式收口初始化与稳定回调热点。
- Phase Scope:
  - 包含：8.1、8.2、8.3 的代码落地
  - 不含：额外功能开发、样式调整、历史阶段回流
- Non-goals:
  - 不修改业务请求语义
  - 不更改 modal 的交互表现与快捷键定义
- Phase Deliverables:
  - lazy init 的 `ChatSessionRequestControl`
  - `useEffectEvent` 驱动的稳定 DOM 事件回调
  - 验证、commit、最终收尾
- Active Execution Wave: 高级模式审计 -> lazy init / stable handler 落地 -> 验证 -> commit -> 最终验证
- Entry Criteria: Phase 7 commit `830477f` 已完成
- Exit Criteria / Done Definition:
  - `ChatSessionRequestControl` 不再在每次 render 执行构造表达式
  - modal `keydown` 监听回调稳定化
  - 验证完成并提交 Phase 8 commit
- Eval Objective: 收口 advanced patterns 热点，不改变外部行为
- Evaluation Surface / Baseline:
  - `useRef(new ChatSessionRequestControl())`
  - `useModalAccessibility()` 的 `useCallback + addEventListener`
- Metric / Rubric:
  - lazy init 边界清晰
  - `useEffectEvent` 落点明确
  - 类型检查、定向 lint、构建通过
- Pass Threshold / Stop Condition: 所有 Phase 8 范围项完成并拿到 fresh verification
- Transition Notes / Next Phase Trigger: Phase 8 commit 完成后执行最终全链路验证与交付总结
- Previous Phase Summary: Phase 7 已完成 JavaScript performance，并提交 `830477f`

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将 Advanced Patterns 收敛为“lazy init + stable event callback”
- Goal: 避免把 Phase 8 扩成更大的 hooks 重构
- Done when: 目标文件、目标规则与无落点项明确
- Deliverables: Phase 8 可执行目标
- Notes: 8.1 落在 request control，8.2/8.3 合并落在 modal accessibility

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认验证策略与沙箱限制
- Goal: 避免把 build 限制误判为代码问题
- Done when: typecheck / eslint / build 的执行策略明确
- Deliverables: 验证策略与环境约束
- Notes: build 在默认沙箱内可能触发 `spawn EPERM`

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 基于 hooks 热点完成 advanced patterns 审计
- Goal: 只改真实初始化与事件回调路径
- Done when: 已定位 `useRef(new ChatSessionRequestControl())` 与 modal `keydown` effect 热点
- Deliverables: 当前阶段上下文结论
- Notes: 当前未发现更高价值的 handler ref 热点

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 8 执行顺序
- Goal: 最小改动覆盖 lazy init 与 stable callback
- Done when: 执行顺序清晰
- Deliverables: 当前阶段执行计划
- Notes: 先处理 request control，再处理 modal accessibility

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 完成 `ChatSessionRequestControl` 的 lazy init
- Goal: 先消除每次 render 的构造表达式开销
- Done when: `useGeneralChatController.ts` / `useKbChatSessionController.ts` 都切换为 lazy ref 初始化
- Deliverables: 两个 session controller hooks
- Notes: 已完成代码修改，当前仍待 fresh verification

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成 modal accessibility 的稳定事件回调
- Goal: 让 Phase 8 代码范围闭环
- Done when: `useModalAccessibility.ts` 使用 `useEffectEvent`
- Deliverables: modal accessibility hook
- Notes: 已完成代码修改，当前仍待 verification 与 commit

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与 Phase 8 结论直接相关的验证
- Goal: 只有在拿到 typecheck / lint / build 证据后才完成本阶段
- Done when: 验证结果支持 advanced patterns 优化结论
- Deliverables: 验证摘要
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/hooks/useModalAccessibility.ts src/hooks/useGeneralChatController.ts src/hooks/useKbChatSessionController.ts` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile status and decide transition
- [ ] Task: 更新状态、归档 Phase 8 计划、提交 commit，并执行最终全链路验证
- Goal: 保留清晰审计轨迹并完成项目收尾
- Done when: Medium/Fine 状态同步、commit 完成、最终验证完成
- Deliverables: 阶段总结、归档引用、最终收尾决策
- Notes: fresh verification 已完成；当前仅剩归档、commit 与最终验证
