# Task Todo - Fine

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-01-waterfalls.md`
  - `archive/perf-phases/TASK_TODO_FINE.phase-01-waterfalls.md`
  - `archive/perf-phases/PROJECT_EXECUTION_STATE.phase-01-waterfalls.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/theme`, `frontend/src/views`, `frontend/src/components/research`, `frontend/src/components/shell`
- Brownfield Context / Codebase Map:
  - `frontend/src/theme/ThemeProvider.tsx` -> `./index`（本地 barrel import）
  - `frontend/src/views/ResearchPage.tsx`（静态导入重面板）
  - `frontend/src/components/research/ArtifactPanel.tsx`（直接依赖 markdown 库）
  - `frontend/src/components/research/ResearchAdvancedEventsPanel.tsx`（Accordion chunk）
  - `frontend/src/components/shell/GeminiShell.tsx`（Sidebar dynamic import，但无用户意图预加载）
  - `frontend/.next/analyze/client.html`（Phase 2 baseline）
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 首次进入相关页面时只加载关键路径 JS，非关键模块在需要时再取
- Why Now / Decision Driver: Phase 2 明确要求 bundle 优化
- Phase Roadmap Summary: 当前仅执行 Phase 2，完成后切换 Phase 3
- Current Phase: Phase 2 - Bundle Size Optimization
- Current Phase Inputs:
  - Phase 1 commit `8e7e152`
  - `npm run analyze` baseline
  - 现有 dynamic import 与静态 import 分布
- Active Execution Wave:
  - 消除本地 barrel import
  - 研究页重面板按需加载
  - Sidebar 用户意图预加载
- Phase Goal: 让非关键 bundle 退出初始加载路径
- Phase Scope:
  - 包含：2.1、2.2、2.3、2.4、2.5
  - 不包含：Phase 3 以后内容
- Non-goals:
  - 不变更页面布局
  - 不改主题语义与配色
- Phase Deliverables:
  - 主题文件直连 import
  - 研究页 `ArtifactPanel` / `ResearchAdvancedEventsPanel` dynamic 化
  - markdown 依赖后移
  - Sidebar preload on intent
  - analyzer / build / typecheck 证据
- Entry Criteria: 已归档 Phase 1；Phase 2 baseline 已取得
- Phase Exit Criteria:
  - local barrel import 清零
  - 研究页非关键面板后移
  - 至少一处用户意图预加载落地
  - 验证完成并提交 commit
- Eval Objective: 下降初始研究页与壳层 bundle 压力
- Evaluation Surface / Baseline:
  - `client.html` 中 research route 初始 chunk 含 Accordion 模块
  - 代码中静态 import `ArtifactPanel` / `ResearchAdvancedEventsPanel`
  - `ThemeProvider.tsx` 导入 `./index`
- Metric / Rubric: 初始 bundle 路径更干净，按需加载边界更清晰，验证通过
- Pass Threshold / Stop Condition: Phase 2 所有目标文件完成并通过验证
- Next Phase Trigger / Transition Notes: Phase 2 commit 完成后刷新为 Phase 3
- Previous Phase Summary: Phase 1 已完成并归档

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将 bundle 优化收敛为明确可执行的文件级任务
- Goal: 避免“优化 bundle”过于宽泛
- Inputs / Dependencies: analyzer 基线、目标文件
- Procedure / Implementation notes: 只针对已定位热点下手
- Output / Artifact: 可执行目标说明
- Done when: 已明确 4 个改动面
- Verification: Medium todo 已同步
- Notes: 4 个改动面分别对应 2.1~2.5

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出 Phase 2 所需依赖与验证约束
- Goal: 让执行与验证保持一致
- Inputs / Dependencies: analyze/build/typecheck、目标文件
- Procedure / Implementation notes: 保留最小改动，优先复用现有动态加载模式
- Output / Artifact: 当前阶段依赖清单
- Done when: 提权需求与验证命令明确
- Verification: `PROJECT_EXECUTION_STATE.md` 将同步
- Notes: analyzer/build 仍需可能提权

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化 analyzer 与代码审计结论
- Goal: 对应真实 bundle 热点
- Inputs / Dependencies: `client.html`、目标源码
- Procedure / Implementation notes:
  - 研究页存在静态导入的非关键面板
  - `ArtifactPanel` 直接持有 markdown 库
  - `ResearchAdvancedEventsPanel` 引入 Accordion 相关 chunk
  - `ThemeProvider.tsx` 存在本地 barrel import
  - `GeminiShell.tsx` 的 Sidebar 已 dynamic，但缺少 user-intent preload
- Output / Artifact: Phase 2 上下文图
- Done when: 每个目标项都能映射到具体文件
- Verification: 目标文件已审阅
- Notes: 不扩展到无证据热点

### 2.2 Break the current phase into executable units
- [x] Task: 拆解 Phase 2 执行单元
- Goal: 保持可跟踪
- Inputs / Dependencies: baseline、目标文件
- Procedure / Implementation notes:
  - 重命名主题文件并改直连 import
  - ResearchPage 改 dynamic imports + conditional rendering
  - ArtifactPanel 复用 MarkdownContent，移除直接 markdown 库 import
  - GeminiShell 加 preload on intent
  - 跑 typecheck/build/analyze 并比较结果
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 3.x/4.x 已细化
- Notes: 优先小步可证据化

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 处理 theme barrel import 与 research 面板动态加载边界
- Goal: 先清掉最明显的 bundle 入口问题
- Inputs / Dependencies:
  - `frontend/src/theme/ThemeProvider.tsx`
  - `frontend/src/theme/index.ts`
  - `frontend/src/views/ResearchPage.tsx`
  - `frontend/src/components/research/ArtifactPanel.tsx`
  - `frontend/src/components/research/ResearchAdvancedEventsPanel.tsx`
- Procedure / Implementation notes:
  - 主题文件改直连 import
  - `ArtifactPanel` / `ResearchAdvancedEventsPanel` 改 dynamic import
  - `ArtifactPanel` 内复用 `MarkdownContent`
- Output / Artifact: 主题与研究页按需加载改动
- Done when: barrel import 消失；研究页非关键面板退出静态入口
- Verification: 搜索结果与构建分析
- Notes:
  - 已完成 `frontend/src/theme/index.ts -> frontend/src/theme/md3Theme.ts`
  - 已完成 `frontend/src/views/ResearchPage.tsx` dynamic import 边界
  - 已完成 `frontend/src/components/research/ArtifactPanel.tsx` 对 markdown 依赖的后移

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 补充 Sidebar user-intent preload、完成验证并提交
- Goal: 完成 2.5 并收口 Phase 2
- Inputs / Dependencies:
  - `frontend/src/components/shell/GeminiShell.tsx`
  - analyzer/build/typecheck
- Procedure / Implementation notes:
  - hoist Sidebar loader
  - 在菜单按钮 hover/focus/touch 时预热 Sidebar chunk
  - 运行 analyze/build/typecheck
- Output / Artifact: preload 改动、验证结果、commit
- Done when: preload 生效且验证完成
- Verification: analyzer/build/typecheck 输出
- Notes:
  - 已完成 `GeminiShell.tsx` 用户意图预热
  - build/analyze 在沙箱内触发 `spawn EPERM`，已提权补跑并通过
  - 当前仅剩 git commit 动作

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与 Phase 2 结论直接相关的验证
- Goal: 防止只改代码不看 bundle 结果
- Inputs / Dependencies: 完成后的代码、analyze/build/typecheck
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑 `npm run build`
  - 跑 `npm run analyze`
  - 对比 `client.html` 中 research route 相关 chunk 变化
- Output / Artifact: Phase 2 验证记录
- Done when: 验证足以支撑 bundle 优化结论
- Verification: 命令输出与 analyzer 片段
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/theme/ThemeProvider.tsx src/theme/md3Theme.ts src/components/research/ArtifactPanel.tsx src/components/shell/GeminiShell.tsx src/views/ResearchPage.tsx` 通过
  - `npm run build` 通过（require_escalated）
  - `npm run analyze` 通过（require_escalated）
  - `client.html` 可提取到：
    - `ArtifactPanel.tsx ... isInitialByEntrypoint:{}`
    - `ResearchAdvancedEventsPanel.tsx ... isInitialByEntrypoint:{}`
    - `InterruptDecisionPanel.tsx ... isInitialByEntrypoint:{}`

### 4.2 Reconcile phase completion and prepare the next step
- [ ] Task: 更新状态、提交 Phase 2 commit，并准备切到 Phase 3
- Goal: 留下完整审计轨迹
- Inputs / Dependencies: 已验证改动、git 工作区
- Procedure / Implementation notes:
  - 更新 active planning files
  - 提交明确 commit
  - 归档 Phase 2 计划
- Output / Artifact: commit + 过渡决策
- Done when: Phase 2 commit 完成，Phase 3 入口明确
- Verification: `git log -1 --stat`
- Notes: 当前 planning files 已到完成态；提交当前 commit 后才可标记完成并刷新为 Phase 3
