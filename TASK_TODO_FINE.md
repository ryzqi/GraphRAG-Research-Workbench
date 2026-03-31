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
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/services`, `frontend/src/views`, `frontend/src/components/research`, `frontend/src/components`
- Brownfield Context / Codebase Map:
  - `frontend/src/services/researchWorkbench.ts`（progress feed / artifacts 汇总）
  - `frontend/src/views/ResearchPage.tsx`
  - `frontend/src/components/research/ArtifactPanel.tsx`
  - `frontend/src/components/IngestionManifestEditor.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: JS 运行时不应在同一渲染周期内对同一数据结构反复排序、过滤与计数。
- Why Now / Decision Driver: Phase 7 明确要求 JavaScript Performance 优化
- Phase Roadmap Summary: 当前仅执行 Phase 7，完成后切换 Phase 8
- Current Phase: Phase 7 - JavaScript Performance
- Current Phase Inputs:
  - Phase 6 commit `567e1af`
  - `researchWorkbench.ts` / `ResearchPage.tsx` 当前实现
  - `ArtifactPanel.tsx` / `IngestionManifestEditor.tsx` 当前遍历方式
- Active Execution Wave:
  - research workbench 结果复用
  - citations 单次分类
  - manifest entries 单次计数
- Phase Goal: 让 JS 层重复计算更少、更可控且不改变输出
- Phase Scope:
  - 包含：7.4、7.6 的代码落地；其余规则做审计
  - 不包含：Phase 8 与项目收尾
- Non-goals:
  - 不调整组件视觉表现
  - 不引入新的缓存层或协议字段
- Phase Deliverables:
  - `researchWorkbench.ts` / `ResearchPage.tsx` 的 progress feed 复用
  - `ArtifactPanel.tsx` 的 citations 单次分类
  - `IngestionManifestEditor.tsx` 的 manifest 单次计数
  - typecheck / eslint / vitest / build 证据
- Entry Criteria: Phase 6 已提交
- Phase Exit Criteria:
  - 重复 progress feed 计算已收敛
  - 双 filter / 双计数已变为单次遍历
  - 验证完成并提交 commit
- Eval Objective: 降低 JS 层重复排序、过滤与计数的开销
- Evaluation Surface / Baseline:
  - `buildResearchCanvasModel()` 再次调用 `buildResearchProgressFeed()`
  - `ArtifactPanel.tsx` 两次 `filter`
  - `validateManifestDraftEntries()` 两次 `filter`
- Metric / Rubric: 复用已算结果、单次遍历边界清晰、验证通过
- Pass Threshold / Stop Condition: Phase 7 所有目标文件完成并通过验证
- Next Phase Trigger / Transition Notes: Phase 7 commit 完成后刷新为 Phase 8
- Previous Phase Summary: Phase 6 已完成并归档

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将 JavaScript Performance 收敛为明确可执行的文件级任务
- Goal: 避免把 Phase 7 扩成泛泛的微优化清扫
- Inputs / Dependencies: 目标源码、Research workbench、manifest 校验、artifact 渲染
- Procedure / Implementation notes: 只处理已定位的重复计算；无高价值项如实记录
- Output / Artifact: 可执行目标说明
- Done when: 已明确改动文件与审计结论
- Verification: Medium todo 已同步
- Notes: 7.4/7.6 为主要代码落点

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出 Phase 7 所需依赖与验证约束
- Goal: 让执行与验证保持一致
- Inputs / Dependencies: typecheck / eslint / vitest / build、目标文件
- Procedure / Implementation notes: 保持最小改动，优先复用现有 memo 与测试
- Output / Artifact: 当前阶段依赖清单
- Done when: 验证命令与提权需求明确
- Verification: `PROJECT_EXECUTION_STATE.md` 已同步
- Notes: build 仍可能需提权

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化 JS 热点审计结论
- Goal: 对应真实重复计算路径
- Inputs / Dependencies: 目标 services / views / components
- Procedure / Implementation notes:
  - `ResearchPage` 已先算 `progressItems`，但 canvas model 仍会再次排序事件
  - `ArtifactPanel` 对同一 citations 数组两次过滤
  - `validateManifestDraftEntries` 为 URL 与 file 数量各做一次完整过滤
- Output / Artifact: Phase 7 上下文图
- Done when: 每个目标项都能映射到具体文件
- Verification: 目标文件已审阅
- Notes: 其他规则暂未发现更高收益落点

### 2.2 Break the current phase into executable units
- [x] Task: 拆解 Phase 7 执行单元
- Goal: 保持可跟踪
- Inputs / Dependencies: baseline、目标文件
- Procedure / Implementation notes:
  - `researchWorkbench.ts` 复用 progress feed，并单次汇总 artifacts
  - `ResearchPage.tsx` 传递已算的 `progressItems`
  - `ArtifactPanel.tsx` / `IngestionManifestEditor.tsx` 单次遍历
  - 跑 typecheck / eslint / vitest / build
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 3.x/4.x 已细化
- Notes: 优先保持现有输出结构不变

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 处理 research workbench 的重复计算路径
- Goal: 先消除同一页面中的重复排序与重复查找
- Inputs / Dependencies:
  - `frontend/src/services/researchWorkbench.ts`
  - `frontend/src/views/ResearchPage.tsx`
- Procedure / Implementation notes:
  - 新增 artifacts 汇总 helper
  - `buildResearchCanvasModel` 支持复用 `progressFeed`
  - `ResearchPage` 传入已有 `progressItems`
- Output / Artifact: progress feed 复用改动
- Done when: research workbench 重复计算已收口
- Verification: typecheck / eslint / vitest / build
- Notes: 已完成代码修改，当前仅待验证

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 完成 citations / manifest 的单次遍历优化
- Goal: 收口 Phase 7
- Inputs / Dependencies:
  - `frontend/src/components/research/ArtifactPanel.tsx`
  - `frontend/src/components/IngestionManifestEditor.tsx`
- Procedure / Implementation notes:
  - citations 分类改为单次循环
  - URL / file 计数改为单次循环
  - 保持错误信息与显示顺序不变
- Output / Artifact: 单次遍历改动
- Done when: 双遍历已消除
- Verification: typecheck / eslint / vitest / build
- Notes: 已完成代码修改，当前仅待验证与 commit

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与 Phase 7 结论直接相关的验证
- Goal: 防止只改代码不验证 JS 热点
- Inputs / Dependencies: 完成后的代码、typecheck / eslint / vitest / build
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑 `npx eslint src/services/researchWorkbench.ts src/views/ResearchPage.tsx src/components/research/ArtifactPanel.tsx src/components/IngestionManifestEditor.tsx`
  - 跑 `npx vitest run src/services/researchWorkbench.test.ts`
  - 跑 `npm run build`
- Output / Artifact: Phase 7 验证记录
- Done when: 验证足以支撑 JavaScript performance 优化结论
- Verification: 命令输出留痕
- Notes: 如 build 触发 `spawn EPERM`，需提权重跑
  - `npm run typecheck` 通过
  - `npx eslint src/services/researchWorkbench.ts src/views/ResearchPage.tsx src/components/research/ArtifactPanel.tsx src/components/IngestionManifestEditor.tsx` 通过
  - `npx vitest run src/services/researchWorkbench.test.ts` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile phase completion and prepare the next step
- [ ] Task: 更新状态、归档 Phase 7 计划、提交 Phase 7 commit，并准备切到 Phase 8
- Goal: 留下完整审计轨迹
- Inputs / Dependencies: 已验证改动、git 工作区
- Procedure / Implementation notes:
  - 更新 active planning files
  - 归档 Phase 7 planning docs
  - 提交明确 commit
  - 刷新为 Phase 8
- Output / Artifact: commit + 过渡决策
- Done when: Phase 7 commit 完成，Phase 8 入口明确
- Verification: `git log -1 --stat`
- Notes: fresh verification 已完成；当前仅剩归档与 commit
