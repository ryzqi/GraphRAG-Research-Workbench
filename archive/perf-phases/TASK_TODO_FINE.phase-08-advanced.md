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
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/hooks`
- Brownfield Context / Codebase Map:
  - `frontend/src/hooks/useModalAccessibility.ts`
  - `frontend/src/hooks/useGeneralChatController.ts`
  - `frontend/src/hooks/useKbChatSessionController.ts`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 请求控制对象和 DOM 事件监听应使用更稳定的高级模式，减少 render 与 effect 周期中的额外开销。
- Why Now / Decision Driver: Phase 8 明确要求 Advanced Patterns 收口
- Phase Roadmap Summary: 当前仅执行 Phase 8，完成后进入最终验证与交付总结
- Current Phase: Phase 8 - Advanced Patterns
- Current Phase Inputs:
  - Phase 7 commit `830477f`
  - `useGeneralChatController.ts` / `useKbChatSessionController.ts` 当前 `useRef(new ChatSessionRequestControl())`
  - `useModalAccessibility.ts` 当前 `useCallback + addEventListener`
- Active Execution Wave:
  - request control lazy init
  - `useEffectEvent` 稳定 DOM 事件回调
- Phase Goal: 让 advanced patterns 在最小范围内落地且不改变行为
- Phase Scope:
  - 包含：8.1、8.2、8.3 的代码落地
  - 不包含：额外功能开发与样式调整
- Non-goals:
  - 不调整 modal 行为与快捷键
  - 不引入新的公共抽象层
- Phase Deliverables:
  - `useGeneralChatController.ts` / `useKbChatSessionController.ts` lazy init
  - `useModalAccessibility.ts` 的 `useEffectEvent`
  - typecheck / eslint / build 证据
- Entry Criteria: Phase 7 已提交
- Phase Exit Criteria:
  - request control 初始化只发生在首次需要时
  - DOM 事件回调稳定化完成
  - 验证完成并提交 commit
- Eval Objective: 用高级模式收口初始化与监听稳定性热点
- Evaluation Surface / Baseline:
  - `useRef(new ChatSessionRequestControl())`
  - `useCallback` 驱动的 `keydown` effect 监听
- Metric / Rubric: lazy init 清晰、stable callback 清晰、验证通过
- Pass Threshold / Stop Condition: Phase 8 所有目标文件完成并通过验证
- Next Phase Trigger / Transition Notes: Phase 8 commit 完成后执行最终全链路验证
- Previous Phase Summary: Phase 7 已完成并归档

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将 Advanced Patterns 收敛为明确可执行的文件级任务
- Goal: 避免把 Phase 8 扩成大范围 hooks 重构
- Inputs / Dependencies: 目标 hooks、React 19 `useEffectEvent`
- Procedure / Implementation notes: 只处理已定位的初始化与监听热点
- Output / Artifact: 可执行目标说明
- Done when: 已明确改动文件与审计结论
- Verification: Medium todo 已同步
- Notes: 8.1/8.2/8.3 都有明确代码落点

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出 Phase 8 所需依赖与验证约束
- Goal: 让执行与验证保持一致
- Inputs / Dependencies: typecheck / eslint / build、React 19
- Procedure / Implementation notes: 保持最小改动，不改业务控制流
- Output / Artifact: 当前阶段依赖清单
- Done when: 验证命令与提权需求明确
- Verification: `PROJECT_EXECUTION_STATE.md` 已同步
- Notes: build 仍可能需提权

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化 advanced patterns 热点审计结论
- Goal: 对应真实初始化与事件监听路径
- Inputs / Dependencies: 目标 hooks
- Procedure / Implementation notes:
  - 两个 session controller hook 都在 render 中执行 `new ChatSessionRequestControl()`
  - modal accessibility 的 keydown 监听会跟随回调依赖走 effect 重订阅
- Output / Artifact: Phase 8 上下文图
- Done when: 每个目标项都能映射到具体文件
- Verification: 目标文件已审阅
- Notes: 当前未发现更高价值的 handler-ref 热点

### 2.2 Break the current phase into executable units
- [x] Task: 拆解 Phase 8 执行单元
- Goal: 保持可跟踪
- Inputs / Dependencies: baseline、目标文件
- Procedure / Implementation notes:
  - request control 改 lazy ref 初始化
  - modal keydown 回调改 `useEffectEvent`
  - 跑 typecheck / eslint / build
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 3.x/4.x 已细化
- Notes: 优先保持 hooks 对外 API 不变

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 处理 request control 的 lazy init
- Goal: 先消除 render 周期内的重复构造表达式
- Inputs / Dependencies:
  - `frontend/src/hooks/useGeneralChatController.ts`
  - `frontend/src/hooks/useKbChatSessionController.ts`
- Procedure / Implementation notes:
  - `useRef<... | null>(null)`
  - 首次访问时显式构造 `ChatSessionRequestControl`
- Output / Artifact: request control lazy init 改动
- Done when: 两个 hook 都完成切换
- Verification: typecheck / eslint / build
- Notes: 已完成代码修改，当前仅待验证

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 完成 modal accessibility 的稳定事件回调
- Goal: 收口 Phase 8
- Inputs / Dependencies:
  - `frontend/src/hooks/useModalAccessibility.ts`
- Procedure / Implementation notes:
  - 使用 `useEffectEvent`
  - 将 effect 依赖收窄到 `isOpen`
- Output / Artifact: stable callback 改动
- Done when: keydown 监听回调稳定化
- Verification: typecheck / eslint / build
- Notes: 已完成代码修改，当前仅待验证与 commit

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与 Phase 8 结论直接相关的验证
- Goal: 防止只改代码不验证 advanced patterns
- Inputs / Dependencies: 完成后的代码、typecheck / eslint / build
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑 `npx eslint src/hooks/useModalAccessibility.ts src/hooks/useGeneralChatController.ts src/hooks/useKbChatSessionController.ts`
  - 跑 `npm run build`
- Output / Artifact: Phase 8 验证记录
- Done when: 验证足以支撑 advanced patterns 优化结论
- Verification: 命令输出留痕
- Notes: 如 build 触发 `spawn EPERM`，需提权重跑
  - `npm run typecheck` 通过
  - `npx eslint src/hooks/useModalAccessibility.ts src/hooks/useGeneralChatController.ts src/hooks/useKbChatSessionController.ts` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile phase completion and prepare the next step
- [ ] Task: 更新状态、归档 Phase 8 计划、提交 Phase 8 commit，并执行最终全链路验证
- Goal: 留下完整审计轨迹并完成项目收尾
- Inputs / Dependencies: 已验证改动、git 工作区
- Procedure / Implementation notes:
  - 更新 active planning files
  - 归档 Phase 8 planning docs
  - 提交明确 commit
  - 执行最终验证
- Output / Artifact: commit + 最终收尾决策
- Done when: Phase 8 commit 完成，最终验证完成
- Verification: `git log -1 --stat`
- Notes: fresh verification 已完成；当前仅剩归档、commit 与最终验证
