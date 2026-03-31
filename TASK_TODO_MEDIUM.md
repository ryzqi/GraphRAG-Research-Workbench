# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference: N/A（当前为首个阶段）
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/app`, `frontend/src/components/providers`, `frontend/src/services`
- Brownfield Context / Codebase Map:
  - `frontend/src/app/(chat)/general-chat/page.tsx`
  - `frontend/src/app/(chat)/kb-chat/page.tsx`
  - `frontend/src/app/(knowledge-bases)/knowledge-bases/[kbId]/page.tsx`
  - `frontend/src/app/(knowledge-bases)/knowledge-bases/[kbId]/documents/new/page.tsx`
  - `frontend/src/services/serverFirstRoutePrefetch.ts`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 首屏路由不要被不必要的 await 链阻塞，预取尽量以 Suspense/并行方式展开
- Why Now / Decision Driver: 用户要求按 Vercel 性能规范逐大类优化，当前先做第 1 类
- Phase Roadmap Summary: 共 8 个阶段；当前阶段完成后进入 Bundle Size Optimization
- Current Phase: Phase 1 - Eliminating Waterfalls
- Phase Goal: 消除当前前端代码中最明显的路由级 waterfall，并补上合理的 Suspense 边界
- Phase Scope:
  - 包含：1.1、1.2、1.4、1.5 在路由首屏预取链路中的落地
  - 不含：bundle、RSC 缓存、重渲染与样式改动
- Non-goals:
  - 不改页面视觉结构
  - 不碰与首屏预取无关的交互重构
- Phase Deliverables:
  - 通用 route prefetch boundary
  - 路由级 fallback promise helper
  - 4 个服务端预取页面改造
  - 当前阶段验证结果与 git commit
- Active Execution Wave: 建立边界组件 -> 改造路由页 -> 验证 -> commit
- Entry Criteria: 已完成前端结构审计；当前工作区干净
- Exit Criteria / Done Definition:
  - 4 个目标路由不再在顶层 await prefetch 后才返回
  - 改动有对应验证证据
  - 当前阶段完成后立即 git commit
- Eval Objective: 以最小改动降低首屏阻塞与 await waterfall 风险
- Evaluation Surface / Baseline:
  - 目标文件 diff
  - `npm run typecheck`
  - 定向 Vitest
  - `npm run build`（如需提权则记录）
- Metric / Rubric: 顶层 await 消除、Suspense 边界存在、验证通过
- Pass Threshold / Stop Condition: 所有 Phase 1 范围内改动完成并验证
- Transition Notes / Next Phase Trigger: Phase 1 commit 完成后，归档当前 todo 并切换到 Phase 2
- Previous Phase Summary: N/A

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将“消除 waterfall”收敛为当前首屏路由预取优化任务
- Goal: 明确 Phase 1 不做混类改动
- Done when: 已写清目标路由、目标规则与完成判据
- Deliverables: 当前阶段范围说明
- Notes: 已确认以 `src/app` 的 4 个 server prefetch 路由为主

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 记录环境与验证约束
- Goal: 避免执行过程中把沙箱问题误判为代码问题
- Done when: 已记录 build / vitest 的 `spawn EPERM` 约束
- Deliverables: 约束与验证策略
- Notes: `npm run typecheck` 可直接运行，build / 默认 vitest 可能需要提权或单线程替代

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 审阅路由页与 `serverFirstRoutePrefetch.ts`
- Goal: 找到真实的 waterfall 入口
- Done when: 已定位到顶层 await prefetch 的共同模式
- Deliverables: 当前阶段上下文结论
- Notes: 4 个路由页都在 page 顶层 await prefetch 后再渲染

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定本阶段执行顺序
- Goal: 用最小改动覆盖 1.1/1.2/1.4/1.5
- Done when: 执行顺序清晰且与代码结构匹配
- Deliverables: 当前阶段执行计划
- Notes: 先抽公共边界，再改路由页，再补测试与验证

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 完成 route prefetch 边界与 promise helper
- Goal: 提供统一、可复用的延迟 await 基础设施
- Done when: 通用边界与 helper 文件落地
- Deliverables: 新增组件/辅助函数
- Notes: 对应 fine todo 的 3.1.x

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成 4 个目标路由改造、验证与 commit
- Goal: 让本阶段真正闭环
- Done when: 所有目标路由改造完成，验证完成，git commit 完成
- Deliverables: 路由改造、验证记录、commit
- Notes: 对应 fine todo 的 3.2.x 与 4.x

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与本阶段结论直接对应的验证
- Goal: 只有在有 fresh verification 的情况下才进入下一阶段
- Done when: 类型检查通过，定向测试通过，构建验证结果明确
- Deliverables: 验证摘要
- Notes: `npm run typecheck`、定向 Vitest、改动文件 ESLint 与提权 build 已通过

### 4.2 Reconcile status and decide transition
- [x] Task: 更新状态、归档计划、提交 commit，并决定是否切换到 Phase 2
- Goal: 保留清晰审计轨迹
- Done when: Medium/Fine 状态同步、commit 完成、下一阶段切换条件明确
- Deliverables: 阶段总结、归档引用、transition 决策
- Notes: 本提交完成后应刷新为 Phase 2 - Bundle Size Optimization
