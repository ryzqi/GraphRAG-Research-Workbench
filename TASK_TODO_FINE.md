# Task Todo - Fine

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference: N/A
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/app`, `frontend/src/components/providers`, `frontend/src/services`
- Brownfield Context / Codebase Map:
  - 目标路由：
    - `frontend/src/app/(chat)/general-chat/page.tsx`
    - `frontend/src/app/(chat)/kb-chat/page.tsx`
    - `frontend/src/app/(knowledge-bases)/knowledge-bases/[kbId]/page.tsx`
    - `frontend/src/app/(knowledge-bases)/knowledge-bases/[kbId]/documents/new/page.tsx`
  - 相关服务：
    - `frontend/src/services/serverFirstRoutePrefetch.ts`
  - 相关 provider：
    - `frontend/src/components/providers/RouteSWRFallbackProvider.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 路由首屏预取不再阻塞整个页面返回，预取结果在真正需要时再消化
- Why Now / Decision Driver: 用户要求先完成大类别 1，并在完成后提交
- Phase Roadmap Summary: 当前仅执行 Phase 1，完成后切换到 Phase 2
- Current Phase: Phase 1 - Eliminating Waterfalls
- Current Phase Inputs:
  - 现有 page.tsx 顶层 await prefetch 模式
  - 可复用的 `RouteSWRFallbackProvider`
  - Vercel React Best Practices 中 async / Suspense 规则
- Active Execution Wave:
  - 新增 route prefetch promise helper
  - 新增 Suspense boundary
  - 改造目标路由并补测试
- Phase Goal: 以最小改动消除当前可识别的路由级 waterfall
- Phase Scope:
  - 包含：延迟 await、Suspense 边界、依赖并行、独立 promise 提前启动
  - 不包含：bundle 大小、客户端重渲染、视觉改造
- Non-goals:
  - 不改 dynamic import 策略（除当前阶段必要变动外）
  - 不改页面视觉结构和文案
- Phase Deliverables:
  - `RoutePrefetchBoundary`
  - `routePrefetch` helper 与测试
  - 4 个 page.tsx 改造
  - 验证与 commit
- Entry Criteria: 当前分支干净；Phase 1 范围已明确
- Phase Exit Criteria:
  - 顶层 await prefetch 从 4 个目标路由移除
  - 页面通过 Suspense 边界消费 fallback promise
  - 验证完成并提交 commit
- Eval Objective: 消除首屏 await waterfall
- Evaluation Surface / Baseline:
  - 代码 diff 中不再有 `const fallback = await prefetch...` 顶层模式
  - `npm run typecheck`
  - 定向 `vitest`
  - `npm run build`
- Metric / Rubric: 最小改动、代码可读、首屏阻塞路径更短
- Pass Threshold / Stop Condition: 当前阶段所有目标文件完成改造并验证
- Next Phase Trigger / Transition Notes: Phase 1 commit 完成后归档当前 todo，刷新为 Phase 2
- Previous Phase Summary: N/A

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将规则 1.1/1.2/1.4/1.5 落到现有 App Router 首屏预取链路
- Goal: 让当前阶段可以直接执行
- Inputs / Dependencies: 目标 page.tsx、`serverFirstRoutePrefetch.ts`
- Procedure / Implementation notes: 只针对真正存在服务端预取的路由页；无预取页面暂不触碰
- Output / Artifact: 可执行目标说明
- Done when: 明确“新边界 + 路由改造 + 验证 + commit”
- Verification: Medium todo 与 roadmap 已同步
- Notes: 规则 1.3（API Routes）当前前端仓库不适用，记为无落点

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出执行当前阶段所需依赖与约束
- Goal: 先暴露沙箱 / 工具问题
- Inputs / Dependencies: npm scripts、当前工作区、沙箱环境
- Procedure / Implementation notes: 基线先跑 typecheck/build/test 观察限制
- Output / Artifact: 当前阶段依赖与限制清单
- Done when: 已确认 build / 默认 vitest 的 spawn 限制
- Verification: `PROJECT_EXECUTION_STATE.md` 已记录
- Notes: 后续优先尝试 targeted vitest 单线程/线程池替代

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 逐个核查 4 个目标 page.tsx 的 await 链
- Goal: 只改真实热点
- Inputs / Dependencies: 目标 page.tsx 与 `serverFirstRoutePrefetch.ts`
- Procedure / Implementation notes:
  - general-chat / kb-chat：顶层 await prefetch
  - knowledge-bases detail：先 await params，再 await prefetch
  - add-documents：先 await params，再 await searchParams，再 await prefetch
- Output / Artifact: 可执行上下文图
- Done when: 每个路由的阻塞点都已定位
- Verification: 目标文件已审阅
- Notes: add-documents 的 params/searchParams 需要合并处理

### 2.2 Break the current phase into executable units
- [x] Task: 拆成可单独验证的执行单元
- Goal: 让执行过程可追踪
- Inputs / Dependencies: 目标上下文、当前阶段规则
- Procedure / Implementation notes:
  - 新增 promise helper
  - 新增 Suspense boundary
  - 改造 4 个路由页
  - 补充纯函数测试
  - 跑验证并提交
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 本文件 3.x/4.x 已细化
- Notes: 保持最小改动，不引入无关抽象

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 新增路由预取 helper 与 Suspense boundary
- Goal: 建立统一的延迟 await 基础设施
- Inputs / Dependencies:
  - `frontend/src/services/serverFirstRoutePrefetch.ts`
  - `frontend/src/components/providers/RouteSWRFallbackProvider.tsx`
- Procedure / Implementation notes:
  - 新增 `frontend/src/services/routePrefetch.ts`
  - 新增 `frontend/src/components/providers/RoutePrefetchBoundary.tsx`
  - helper 负责提前启动 promise、统一 search param 提取
  - boundary 负责在 Suspense 内消费 promise 并注入 SWR fallback
- Output / Artifact: 新增 helper / boundary 文件
- Done when: 可被 4 个 page.tsx 直接复用
- Verification: `npm run typecheck` 通过；`src/services/routePrefetch.test.ts` 已覆盖 helper
- Notes: 已新增 `frontend/src/components/providers/RoutePrefetchBoundary.tsx` 与 `frontend/src/services/routePrefetch.ts`

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 改造 4 个 page.tsx 并补充定向测试
- Goal: 把抽象真正落到当前路由
- Inputs / Dependencies:
  - 新增 helper / boundary
  - 4 个目标 page.tsx
- Procedure / Implementation notes:
  - 移除 page 顶层 `await prefetch...`
  - 顶层直接启动 fallback promise
  - 用 `RoutePrefetchBoundary` 包裹原页面内容
  - 补 `frontend/src/services/routePrefetch.test.ts`
- Output / Artifact: 路由改造与测试文件
- Done when: 4 个目标 page.tsx 全部切换到 promise boundary 模式
- Verification: `src/app` 下已无 `await prefetch` 路由模式；`routePrefetch.test.ts` 6 项通过
- Notes: 仅改造有 server prefetch 的 4 个路由页，未触碰其他页面

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与本阶段结论直接相关的验证
- Goal: 防止把“已修改未验证”误报为完成
- Inputs / Dependencies: 完成后的代码、npm scripts、vitest 命令
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑定向 `vitest`（优先单线程/非 fork）
  - 跑 `npm run build`；若需提权则记录
- Output / Artifact: 当前阶段验证记录
- Done when: 验证结果足以支撑“已验证通过”或明确“受限未执行”
- Verification: 命令输出留痕
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint <phase-1-files>` 通过
  - `npx vitest run src/services/routePrefetch.test.ts` 通过（6 tests）
  - `npm run build` 提权后通过

### 4.2 Reconcile phase completion and prepare the next step
- [x] Task: 同步 todo 状态、提交 Phase 1 commit，并准备 Phase 2 切换
- Goal: 留下完整审计轨迹
- Inputs / Dependencies: 已验证的改动、git 工作区
- Procedure / Implementation notes:
  - 更新 medium/fine 完成状态
  - `git status` 确认范围
  - 提交明确的 Phase 1 commit message
  - 归档当前 todo，刷新为 Phase 2
- Output / Artifact: commit + 阶段切换决策
- Done when: 当前阶段 commit 已完成，下一阶段入口明确
- Verification: `git log -1 --stat`
- Notes: 当前提交应对应 Phase 1 完成点；提交后刷新为 Phase 2
