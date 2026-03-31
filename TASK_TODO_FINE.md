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
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/providers`, `frontend/src/services`, `frontend/src/views`, `frontend/src/components/research`
- Brownfield Context / Codebase Map:
  - `frontend/src/services/http.ts`（API base URL 唯一事实源）
  - `frontend/src/providers/AppProviders.tsx`（全局 providers 入口）
  - `frontend/src/views/KbChatPage.tsx`（会话头部时间文本）
  - `frontend/src/views/ExtensionsPage.tsx`（扩展详情时间文本 + 左侧列表）
  - `frontend/src/views/KnowledgeBasesPage.tsx`（知识库卡片网格）
  - `frontend/src/components/research/ResearchProgressFeed.tsx`（研究进度列表）
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 渲染层不应在高频重渲染或长列表中持续做可避免的格式化、布局与连接准备工作。
- Why Now / Decision Driver: Phase 6 明确要求 rendering performance 优化
- Phase Roadmap Summary: 当前仅执行 Phase 6，完成后切换 Phase 7
- Current Phase: Phase 6 - Rendering Performance
- Current Phase Inputs:
  - Phase 5 commit `53a8dd2`
  - `http.ts` 当前 API base URL 逻辑
  - `KbChatPage.tsx` / `ExtensionsPage.tsx` 当前时间文本渲染方式
  - `KnowledgeBasesPage.tsx` / `ResearchProgressFeed.tsx` / `ExtensionsPage.tsx` 当前列表渲染边界
- Active Execution Wave:
  - React DOM resource hints
  - 时间 formatter hoist + leaf hydration mismatch suppress
  - 长列表 `content-visibility`
- Phase Goal: 让渲染热路径更轻、更可预测且不改变 UI 表现
- Phase Scope:
  - 包含：6.2、6.3、6.6、6.10 的代码落地；其余规则做审计
  - 不包含：Phase 7 及之后内容
- Non-goals:
  - 不调整配色、间距、排版与交互动线
  - 不引入新的 hydration fallback 层或双轨渲染逻辑
- Phase Deliverables:
  - `http.ts` 的 API origin 导出
  - `AppProviders.tsx` 的 React DOM resource hints
  - `KbChatPage.tsx` / `ExtensionsPage.tsx` 的 formatter hoist + leaf suppress
  - `KnowledgeBasesPage.tsx` / `ExtensionsPage.tsx` / `ResearchProgressFeed.tsx` 的 `content-visibility`
  - typecheck / eslint / build 证据
- Entry Criteria: Phase 5 已提交
- Phase Exit Criteria:
  - resource hints 已接线
  - 时间文本 mismatch 已收口到 leaf 节点
  - 长列表项惰性渲染已落地
  - 验证完成并提交 commit
- Eval Objective: 降低列表渲染和 hydration 噪音，缩短 API 首连准备路径
- Evaluation Surface / Baseline:
  - `AppProviders.tsx` 缺少 `prefetchDNS` / `preconnect`
  - `KbChatPage.tsx` 与 `ExtensionsPage.tsx` 在 render 阶段直接格式化时间
  - 三处列表项缺少 `content-visibility`
- Metric / Rubric: 资源提示边界清晰、formatter hoist、生效的 leaf suppress、列表惰性渲染、验证通过
- Pass Threshold / Stop Condition: Phase 6 所有目标文件完成并通过验证
- Next Phase Trigger / Transition Notes: Phase 6 commit 完成后刷新为 Phase 7
- Previous Phase Summary: Phase 5 已完成并提交 `53a8dd2`

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将 rendering performance 收敛为明确可执行的文件级任务
- Goal: 避免把 Phase 6 扩成全局 hydration 重构
- Inputs / Dependencies: 目标源码、React 19 resource hints、长列表页面
- Procedure / Implementation notes: 只处理真实热路径；无高价值规则如实记录
- Output / Artifact: 可执行目标说明
- Done when: 已明确改动文件与审计结论
- Verification: Medium todo 已同步
- Notes: 6.2/6.3/6.6/6.10 为主要代码落点

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出 Phase 6 所需依赖与验证约束
- Goal: 让执行与验证保持一致
- Inputs / Dependencies: typecheck / eslint / build、React 19、目标文件
- Procedure / Implementation notes: 保持最小改动，复用现有 API base URL 事实源
- Output / Artifact: 当前阶段依赖清单
- Done when: resource hints 与验证命令明确
- Verification: `PROJECT_EXECUTION_STATE.md` 已同步
- Notes: build 仍可能需提权

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化 rendering 热点审计结论
- Goal: 对应真实渲染路径
- Inputs / Dependencies: 目标 views / providers / services
- Procedure / Implementation notes:
  - `KbChatPage` 在 JSX 中直接输出当前时间
  - `ExtensionsPage` 直接在 render 中 `toLocaleString()`
  - 知识库卡片、扩展列表、研究进度列表都可能增长
  - `AppProviders` 适合作为 resource hints 的全局接入点
- Output / Artifact: Phase 6 上下文图
- Done when: 每个目标项都能映射到具体文件
- Verification: 目标文件已审阅
- Notes: 不扩展到无脚本、无 SVG 动画的页面

### 2.2 Break the current phase into executable units
- [x] Task: 拆解 Phase 6 执行单元
- Goal: 保持可跟踪
- Inputs / Dependencies: baseline、目标文件
- Procedure / Implementation notes:
  - `http.ts` 暴露 API origin
  - `AppProviders.tsx` 补 `prefetchDNS` / `preconnect`
  - `KbChatPage.tsx` / `ExtensionsPage.tsx` hoist formatter 并在 leaf suppress
  - 三个列表补 `content-visibility`
  - 跑 typecheck / eslint / build
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 3.x/4.x 已细化
- Notes: 优先保持现有 UI 与文案不变

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 完成 resource hints 与时间文本 hydration 收口
- Goal: 先处理 API 首连与预期 mismatch 噪音
- Inputs / Dependencies:
  - `frontend/src/services/http.ts`
  - `frontend/src/providers/AppProviders.tsx`
  - `frontend/src/views/KbChatPage.tsx`
  - `frontend/src/views/ExtensionsPage.tsx`
- Procedure / Implementation notes:
  - 导出 API origin
  - 用 React 19 `prefetchDNS` / `preconnect` 发出资源提示
  - 模块级 hoist formatter
  - 只在时间文本 leaf 节点使用 `suppressHydrationWarning`
- Output / Artifact: resource hints、formatter hoist、leaf suppress
- Done when: API origin 与时间文本热路径改动完成
- Verification: typecheck / eslint / build
- Notes: 已完成代码修改，当前仅待验证

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 完成长列表 `content-visibility` 与审计留痕
- Goal: 收口 Phase 6
- Inputs / Dependencies:
  - `frontend/src/views/KnowledgeBasesPage.tsx`
  - `frontend/src/views/ExtensionsPage.tsx`
  - `frontend/src/components/research/ResearchProgressFeed.tsx`
- Procedure / Implementation notes:
  - 列表项补充 `contentVisibility: 'auto'`
  - 结合 `containIntrinsicSize` 降低跳动
  - 将无高价值规则记录为审计结论，不强行扩项
- Output / Artifact: 列表项惰性渲染改动、审计结果
- Done when: 列表热路径改动完成
- Verification: typecheck / eslint / build
- Notes: 已完成代码修改，当前仅待验证与 commit

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与 Phase 6 结论直接相关的验证
- Goal: 防止只改代码不验证 rendering 路径
- Inputs / Dependencies: 完成后的代码、typecheck / eslint / build
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑 `npx eslint src/services/http.ts src/providers/AppProviders.tsx src/views/KbChatPage.tsx src/views/ExtensionsPage.tsx src/views/KnowledgeBasesPage.tsx src/components/research/ResearchProgressFeed.tsx`
  - 跑 `npm run build`
- Output / Artifact: Phase 6 验证记录
- Done when: 验证足以支撑 rendering performance 优化结论
- Verification: 命令输出留痕
- Notes: 如 build 触发 `spawn EPERM`，需提权重跑
  - `npm run typecheck` 通过
  - `npx eslint src/services/http.ts src/providers/AppProviders.tsx src/views/KbChatPage.tsx src/views/ExtensionsPage.tsx src/views/KnowledgeBasesPage.tsx src/components/research/ResearchProgressFeed.tsx` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile phase completion and prepare the next step
- [ ] Task: 更新状态、归档 Phase 6 计划、提交 Phase 6 commit，并准备切到 Phase 7
- Goal: 留下完整审计轨迹
- Inputs / Dependencies: 已验证改动、git 工作区
- Procedure / Implementation notes:
  - 更新 active planning files
  - 归档 Phase 6 planning docs
  - 提交明确 commit
  - 刷新为 Phase 7
- Output / Artifact: commit + 过渡决策
- Done when: Phase 6 commit 完成，Phase 7 入口明确
- Verification: `git log -1 --stat`
- Notes: fresh verification 已完成；当前仅剩归档与 commit
