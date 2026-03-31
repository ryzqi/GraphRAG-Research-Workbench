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
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/providers`, `frontend/src/services`, `frontend/src/views`, `frontend/src/components/research`
- Brownfield Context / Codebase Map:
  - `frontend/src/services/http.ts`
  - `frontend/src/providers/AppProviders.tsx`
  - `frontend/src/views/KbChatPage.tsx`
  - `frontend/src/views/ExtensionsPage.tsx`
  - `frontend/src/views/KnowledgeBasesPage.tsx`
  - `frontend/src/components/research/ResearchProgressFeed.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 渲染层不应在长列表中做不必要的布局/绘制，也不应在时间文本等预期不稳定内容上持续制造 hydration mismatch 噪音；跨域 API 首次连接应尽量提前。
- Why Now / Decision Driver: Phase 5 已提交，按用户要求切入 Phase 6 - Rendering Performance。
- Phase Roadmap Summary: 当前阶段完成后，进入 Phase 7 - JavaScript Performance。
- Current Phase: Phase 6 - Rendering Performance
- Phase Goal: 依据渲染热路径，收敛 hydration mismatch、资源提示与长列表渲染成本。
- Phase Scope:
  - 包含：6.2、6.3、6.6、6.10 的代码落地
  - 审计：6.1、6.4、6.5、6.7、6.8、6.9、6.11 是否存在高价值最小改动
  - 不含：视觉样式变更、交互流程改版、Phase 7 及之后内容
- Non-goals:
  - 不修改配色、布局结构与信息架构
  - 不为了覆盖规则而引入更大范围的 hydration 兼容层
- Phase Deliverables:
  - 长列表 `content-visibility`
  - 静态 `Intl.DateTimeFormat` hoist
  - leaf 级 `suppressHydrationWarning`
  - React DOM resource hints
  - 验证与 commit
- Active Execution Wave: 渲染热点审计 -> 最小改动落地 -> 验证 -> commit
- Entry Criteria: Phase 5 commit `53a8dd2` 已完成
- Exit Criteria / Done Definition:
  - 列表热路径已补充 `content-visibility`
  - 时间文本 mismatch 已收敛到 leaf 节点
  - API origin 已补 React DOM resource hints
  - 验证完成并提交 Phase 6 commit
- Eval Objective: 缩短长列表首屏绘制与 API 首连准备路径，减少预期 hydration mismatch 对调试噪音的干扰
- Evaluation Surface / Baseline:
  - `KbChatPage.tsx` 直接渲染当前时间
  - `ExtensionsPage.tsx` 直接在 render 中做 `toLocaleString()`
  - `KnowledgeBasesPage.tsx` / `ResearchProgressFeed.tsx` / `ExtensionsPage.tsx` 列表项没有 `content-visibility`
  - `AppProviders.tsx` 尚未发出 API origin resource hints
- Metric / Rubric:
  - 列表项惰性布局边界清晰
  - formatter 实例 hoist 到模块级
  - 预期 mismatch 只在 leaf 节点抑制
  - typecheck、定向 lint、build 通过
- Pass Threshold / Stop Condition: 所有 Phase 6 范围项完成并拿到 fresh verification
- Transition Notes / Next Phase Trigger: Phase 6 commit 完成后切换到 Phase 7
- Previous Phase Summary: Phase 5 已完成 rerender 优化，并提交 `53a8dd2`

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将 rendering performance 收敛为“长列表惰性渲染 + hydration mismatch 收口 + resource hints”
- Goal: 避免把 Phase 6 扩成全站 UI 重写
- Done when: 目标文件、目标规则与无落点项明确
- Deliverables: Phase 6 可执行目标
- Notes: 本轮只处理真实热路径，不对低收益规则强行落地

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认验证策略与沙箱限制
- Goal: 避免把 build 限制误判为代码问题
- Done when: typecheck / eslint / build 的执行策略明确
- Deliverables: 验证策略与环境约束
- Notes: build 在默认沙箱内可能触发 `spawn EPERM`

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 基于热点组件与页面完成 rendering 审计
- Goal: 只改真实热路径
- Done when: 已定位当前时间文本 mismatch、列表项缺失 `content-visibility`、API origin 缺失 resource hints
- Deliverables: 当前阶段上下文结论
- Notes: 6.1/6.4/6.5/6.7/6.8/6.9/6.11 本轮暂无更高价值最小改动

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 6 执行顺序
- Goal: 最小改动覆盖 resource hints、hydration、长列表渲染
- Done when: 执行顺序清晰
- Deliverables: 当前阶段执行计划
- Notes: 先补 resource hints，再收口时间文本，再扩长列表 `content-visibility`

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 完成 API origin resource hints 与时间格式化 hoist
- Goal: 先收口 API 首连与 hydration 文本热点
- Done when: `http.ts` / `AppProviders.tsx` / `KbChatPage.tsx` / `ExtensionsPage.tsx` 完成落地
- Deliverables: API origin 提示、静态 formatter、leaf 级 `suppressHydrationWarning`
- Notes: 已完成代码修改，当前仍待 fresh verification

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成长列表 `content-visibility` 与阶段审计结论
- Goal: 让 Phase 6 代码范围闭环
- Done when: `KnowledgeBasesPage.tsx`、`ExtensionsPage.tsx`、`ResearchProgressFeed.tsx` 列表项补充惰性渲染边界
- Deliverables: 列表项渲染性能改动、审计结论
- Notes: 已完成代码修改，当前仍待 verification 与 commit

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与 Phase 6 结论直接相关的验证
- Goal: 只有在拿到 typecheck / lint / build 证据后才完成本阶段
- Done when: 验证结果支持 rendering performance 优化结论
- Deliverables: 验证摘要
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/services/http.ts src/providers/AppProviders.tsx src/views/KbChatPage.tsx src/views/ExtensionsPage.tsx src/views/KnowledgeBasesPage.tsx src/components/research/ResearchProgressFeed.tsx` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile status and decide transition
- [ ] Task: 更新状态、归档 Phase 6 计划、提交 commit，并决定是否切换到 Phase 7
- Goal: 保留清晰审计轨迹
- Done when: Medium/Fine 状态同步、commit 完成、Phase 7 入口明确
- Deliverables: 阶段总结、归档引用、transition 决策
- Notes: fresh verification 已完成；当前仅剩归档与 commit
