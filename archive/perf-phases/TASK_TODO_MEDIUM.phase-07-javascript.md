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
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/services`, `frontend/src/views`, `frontend/src/components/research`, `frontend/src/components`
- Brownfield Context / Codebase Map:
  - `frontend/src/services/researchWorkbench.ts`
  - `frontend/src/views/ResearchPage.tsx`
  - `frontend/src/components/research/ArtifactPanel.tsx`
  - `frontend/src/components/IngestionManifestEditor.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: JS 运行时不应对同一数组做可避免的重复排序、重复过滤或重复统计。
- Why Now / Decision Driver: Phase 6 已提交，按用户要求切入 Phase 7 - JavaScript Performance。
- Phase Roadmap Summary: 当前阶段完成后，进入 Phase 8 - Advanced Patterns。
- Current Phase: Phase 7 - JavaScript Performance
- Phase Goal: 依据真实热点，收敛重复遍历、重复排序与重复函数调用。
- Phase Scope:
  - 包含：7.4、7.6 的代码落地
  - 审计：7.1、7.2、7.3、7.5、7.7、7.8、7.9、7.10、7.11、7.12、7.13、7.14 是否存在高价值最小改动
  - 不含：Phase 8 与最终收尾内容
- Non-goals:
  - 不改动 UI 结构、文案与返回协议
  - 不把本阶段扩展为更大规模的数据层重构
- Phase Deliverables:
  - `researchWorkbench.ts` / `ResearchPage.tsx` 的重复计算收敛
  - `ArtifactPanel.tsx` / `IngestionManifestEditor.tsx` 的单次遍历优化
  - 验证与 commit
- Active Execution Wave: JS 热点审计 -> 单次遍历/复用优化 -> 验证 -> commit
- Entry Criteria: Phase 6 commit `567e1af` 已完成
- Exit Criteria / Done Definition:
  - research workbench 不再重复构建 progress feed
  - citations 与 manifest counts 改为单次遍历
  - 验证完成并提交 Phase 7 commit
- Eval Objective: 缩短 JS 层的重复计算路径，不改变外部行为
- Evaluation Surface / Baseline:
  - `buildResearchCanvasModel()` 会再次调用 `buildResearchProgressFeed()`
  - `ArtifactPanel.tsx` 对 citations 做两次 filter
  - `validateManifestDraftEntries()` 对 entries 做两次 filter
- Metric / Rubric:
  - 重复排序与重复过滤消除
  - 单次遍历边界清晰
  - 类型检查、定向 lint、相关测试、构建通过
- Pass Threshold / Stop Condition: 所有 Phase 7 范围项完成并拿到 fresh verification
- Transition Notes / Next Phase Trigger: Phase 7 commit 完成后切换到 Phase 8
- Previous Phase Summary: Phase 6 已完成 rendering performance，并提交 `567e1af`

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将 JavaScript Performance 收敛为“复用已算结果 + 单次遍历”
- Goal: 避免把 Phase 7 扩成全站算法重写
- Done when: 目标文件、目标规则与无落点项明确
- Deliverables: Phase 7 可执行目标
- Notes: 本轮以 7.4、7.6 为主要代码落点

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认验证策略与沙箱限制
- Goal: 避免把 build 限制误判为代码问题
- Done when: typecheck / eslint / vitest / build 的执行策略明确
- Deliverables: 验证策略与环境约束
- Notes: build 在默认沙箱内可能触发 `spawn EPERM`

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 基于热点服务与组件完成 JS 性能审计
- Goal: 只改真实重复计算路径
- Done when: 已定位重复 progress feed、双 filter、双计数等热点
- Deliverables: 当前阶段上下文结论
- Notes: 其他低收益项以审计结论处理，不强行扩项

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 7 执行顺序
- Goal: 最小改动覆盖重复计算与单次遍历
- Done when: 执行顺序清晰
- Deliverables: 当前阶段执行计划
- Notes: 先处理 research workbench，再处理 citations / manifest 遍历

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 完成 research workbench 的重复计算收口
- Goal: 先消除同一渲染周期内的重复排序与重复 artifacts 查找
- Done when: `ResearchPage.tsx` 复用 `progressItems`，`researchWorkbench.ts` 改为单次 artifacts 汇总
- Deliverables: `researchWorkbench.ts`、`ResearchPage.tsx`
- Notes: 已完成代码修改，当前仍待 fresh verification

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成 citations / manifest entries 的单次遍历优化
- Goal: 让 Phase 7 代码范围闭环
- Done when: `ArtifactPanel.tsx` 与 `IngestionManifestEditor.tsx` 从双遍历改为单次遍历
- Deliverables: `ArtifactPanel.tsx`、`IngestionManifestEditor.tsx`
- Notes: 已完成代码修改，当前仍待 verification 与 commit

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与 Phase 7 结论直接相关的验证
- Goal: 只有在拿到 typecheck / lint / test / build 证据后才完成本阶段
- Done when: 验证结果支持 JS performance 优化结论
- Deliverables: 验证摘要
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/services/researchWorkbench.ts src/views/ResearchPage.tsx src/components/research/ArtifactPanel.tsx src/components/IngestionManifestEditor.tsx` 通过
  - `npx vitest run src/services/researchWorkbench.test.ts` 通过
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile status and decide transition
- [ ] Task: 更新状态、归档 Phase 7 计划、提交 commit，并决定是否切换到 Phase 8
- Goal: 保留清晰审计轨迹
- Done when: Medium/Fine 状态同步、commit 完成、Phase 8 入口明确
- Deliverables: 阶段总结、归档引用、transition 决策
- Notes: fresh verification 已完成；当前仅剩归档与 commit
