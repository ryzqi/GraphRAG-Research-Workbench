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
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/app`, `frontend/src/services`, `frontend/src/lib`
- Brownfield Context / Codebase Map:
  - `frontend/src/services/http.ts`
  - `frontend/src/services/serverFirstRoutePrefetch.ts`
  - `frontend/src/services/chats.ts`
  - `frontend/src/services/knowledgeBases.ts`
  - `frontend/src/services/ingestionBatches.ts`
  - `frontend/src/services/bootstrapSubmissions.ts`
  - `frontend/src/app/(chat)/*/page.tsx`
  - `frontend/src/app/(knowledge-bases)/*/page.tsx`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 减少服务端预取链路中的重复 GET 与被随机 header 打散的缓存命中，同时保持现有页面行为与数据契约不变。
- Why Now / Decision Driver: Phase 2 已提交，按用户要求切入 Phase 3 - Server-Side Performance。
- Phase Roadmap Summary: 当前阶段完成后，进入 Phase 4 - Client-Side Data Fetching。
- Current Phase: Phase 3 - Server-Side Performance
- Phase Goal: 依据 App Router 当前结构，收敛 server-prefetch 链路中的 cache / dedupe / serialization 热点。
- Phase Scope:
  - 包含：3.3、3.4、3.8 的代码落地；3.6/3.7 维持已有并行抓取；3.1/3.2/3.5/3.9 做审计结论留痕
  - 不含：客户端数据获取、视觉改造、接口协议重写
- Non-goals:
  - 不新增 server action
  - 不改动页面结构、风格与交互语义
- Phase Deliverables:
  - cache-friendly server GET 选项
  - 共享 `serverPrefetchCache.ts`
  - `serverFirstRoutePrefetch.ts` 统一改走共享 wrapper
  - targeted tests / build / typecheck / eslint 证据与 commit
- Active Execution Wave: apiFetch cache key 收敛 -> server prefetch cache layer -> 验证 -> commit
- Entry Criteria: Phase 2 commit `7f5eee0` 已完成；Phase 2 planning files 已归档
- Exit Criteria / Done Definition:
  - server-prefetch 可缓存 GET 不再默认携带随机 request id header
  - 存在共享的 `React.cache()` server prefetch wrapper
  - 动态状态 GET 继续 `no-store`，静态元数据 GET 引入短 TTL revalidate
  - 验证完成并提交 Phase 3 commit
- Eval Objective: 缩短服务端预取重复工作路径并提升 cache-friendly 稳定性
- Evaluation Surface / Baseline:
  - `apiFetch` 当前对所有请求都加 `X-Request-Id`
  - `serverFirstRoutePrefetch.ts` 当前直接依赖原始 GET service
  - 当前无共享的 server-prefetch cache module
- Metric / Rubric:
  - server-prefetch GET 入口更稳定
  - 请求内去重与短 TTL server cache 边界清晰
  - 类型检查、定向测试、构建通过
- Pass Threshold / Stop Condition: 所有 Phase 3 范围项完成并拿到 fresh verification
- Transition Notes / Next Phase Trigger: Phase 3 commit 完成后切换到 Phase 4
- Previous Phase Summary: Phase 2 已完成 bundle size optimization，并提交 `7f5eee0`

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: 将服务端性能收敛到“cache-friendly GET + 共享 prefetch cache + 请求内去重”
- Goal: 避免把 Phase 3 扩成后端接口或客户端数据重构
- Done when: 目标文件、目标规则与无落点项都明确
- Deliverables: Phase 3 可执行目标
- Notes: 3.1/3.2/3.5/3.9 以审计结论处理；本轮代码落点聚焦 3.3/3.4/3.8

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: 确认验证策略与沙箱限制
- Goal: 避免把 spawn 限制误判为代码问题
- Done when: typecheck / eslint / vitest / build 的执行策略明确
- Deliverables: 验证策略与环境约束
- Notes: vitest / build 在默认沙箱内会触发 `spawn EPERM`，需按需提权

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: 基于 `http.ts` 与 `serverFirstRoutePrefetch.ts` 完成 server-side 热点审计
- Goal: 只改真实的服务端预取热点
- Done when: 已定位随机 request header、缺少共享 cache layer、以及现有 Promise.all 并行边界
- Deliverables: 当前阶段上下文结论
- Notes: 当前 App Router 仅通过 route prefetch 触达服务端数据链路

### 2.2 Establish the execution plan for this phase
- [x] Task: 制定 Phase 3 执行顺序
- Goal: 最小改动覆盖 cache / dedupe / verification
- Done when: 执行顺序清晰
- Deliverables: 当前阶段执行计划
- Notes: 先收敛 fetch options，再新增 shared cache module，最后替换 prefetch 调用并验证

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: 让 server-prefetch GET 具备稳定缓存键，并建立共享 server cache 模块
- Goal: 先消除被随机 header 打散的 cache hit
- Done when: `apiFetch` 可关闭 request id header，`serverPrefetchCache.ts` 落地
- Deliverables: `http.ts`、`serverPrefetchCache.ts`、相关 GET helper 签名更新
- Notes: 已完成 `includeRequestIdHeader` 与 `React.cache()` 包装层

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: 完成 route prefetch 接线、保留现有并行抓取并收口验证
- Goal: 让 Phase 3 真正闭环
- Done when: `serverFirstRoutePrefetch.ts` 统一改走共享 wrapper，验证通过，commit 待执行
- Deliverables: server prefetch 改动、验证结果、commit
- Notes: 3.6 / 3.7 的 Promise.all 并行抓取保持不变；当前仅待执行 git commit

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: 运行与 Phase 3 结论直接相关的验证
- Goal: 只有在拿到 typecheck / targeted tests / build 证据后才完成本阶段
- Done when: 验证结果支持 server-side 优化结论
- Deliverables: 验证摘要
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/services/http.ts src/services/http.test.ts src/services/chats.ts src/services/knowledgeBases.ts src/services/ingestionBatches.ts src/services/bootstrapSubmissions.ts src/services/serverPrefetchCache.ts src/services/serverFirstRoutePrefetch.ts` 通过
  - `npx vitest run src/services/http.test.ts src/services/routePrefetch.test.ts` 通过（require_escalated；sandbox 内 `spawn EPERM`）
  - `npm run build` 通过（require_escalated；sandbox 内 `spawn EPERM`）

### 4.2 Reconcile status and decide transition
- [ ] Task: 更新状态、归档 Phase 3 计划、提交 commit，并决定是否切换到 Phase 4
- Goal: 保留清晰审计轨迹
- Done when: Medium/Fine 状态同步、commit 完成、Phase 4 入口明确
- Deliverables: 阶段总结、归档引用、transition 决策
- Notes: 当前 planning files 已更新为 Phase 3 完成态；提交当前 commit 后才可标记完成并刷新到 Phase 4
