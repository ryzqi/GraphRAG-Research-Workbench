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
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md`, `TASK_TODO_MEDIUM.md`, `TASK_TODO_FINE.md`, `PROJECT_EXECUTION_STATE.md`
- Project Modules: `frontend/src/app`, `frontend/src/services`, `frontend/src/lib`
- Brownfield Context / Codebase Map:
  - `frontend/src/services/http.ts`（当前对所有请求注入随机 `X-Request-Id`）
  - `frontend/src/services/serverFirstRoutePrefetch.ts`（服务端预取入口）
  - `frontend/src/services/chats.ts`（recent chats）
  - `frontend/src/services/knowledgeBases.ts`（selectable / detail / ingestion state）
  - `frontend/src/services/ingestionBatches.ts`（latest batch）
  - `frontend/src/services/bootstrapSubmissions.ts`（bootstrap submission）
  - `frontend/src/app/(chat)/*/page.tsx` 与 `frontend/src/app/(knowledge-bases)/*/page.tsx`（server prefetch 消费方）
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 服务端预取链路不应因为随机 header 与缺少共享 cache layer 而重复做相同 GET 工作
- Why Now / Decision Driver: Phase 3 明确要求 server-side performance
- Phase Roadmap Summary: 当前仅执行 Phase 3，完成后切换 Phase 4
- Current Phase: Phase 3 - Server-Side Performance
- Current Phase Inputs:
  - Phase 2 commit `7f5eee0`
  - `http.ts` / `serverFirstRoutePrefetch.ts` / 相关 GET helper 当前实现
  - 既有 `Promise.all` 并行抓取边界
- Active Execution Wave:
  - 收敛 cache-friendly GET 选项
  - 引入共享 server prefetch cache
  - 保留现有并行抓取并完成验证
- Phase Goal: 让 server-prefetch 数据路径更稳定、更少重复工作且不改变客户端契约
- Phase Scope:
  - 包含：3.3、3.4、3.8 的代码落地；3.6/3.7 审计确认继续沿用；3.1/3.2/3.5/3.9 留痕说明
  - 不包含：Phase 4 及之后内容
- Non-goals:
  - 不新增 server action
  - 不改动页面 UI、SWR key、接口字段与展示逻辑
- Phase Deliverables:
  - `ApiFetchOptions.includeRequestIdHeader`
  - `serverPrefetchCache.ts`
  - 相关 GET helper 的 server-only options 透传
  - `serverFirstRoutePrefetch.ts` 的共享 wrapper 接线
  - typecheck / eslint / targeted vitest / build 证据
- Entry Criteria: Phase 2 已提交并归档
- Phase Exit Criteria:
  - 可缓存 server GET 不再默认带随机 request id header
  - 共享 `React.cache()` wrapper 已落地
  - server-prefetch 入口已统一走共享 cache layer
  - 验证完成并提交 commit
- Eval Objective: 降低服务端重复 GET 与缓存键抖动
- Evaluation Surface / Baseline:
  - `apiFetch` 为所有请求注入随机 `X-Request-Id`
  - `serverFirstRoutePrefetch.ts` 直接依赖原始 GET service
  - 无模块级 server prefetch cache 配置
- Metric / Rubric: cache 边界更清晰、请求签名更稳定、验证通过
- Pass Threshold / Stop Condition: Phase 3 所有目标文件完成并通过验证
- Next Phase Trigger / Transition Notes: Phase 3 commit 完成后刷新为 Phase 4
- Previous Phase Summary: Phase 2 已完成并归档

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 将 server-side performance 收敛为明确可执行的文件级任务
- Goal: 避免把“服务端性能优化”扩成接口重构
- Inputs / Dependencies: 目标源码、React/Next cache 使用约束
- Procedure / Implementation notes: 只处理 server-prefetch 热点；无落点项用审计结论说明
- Output / Artifact: 可执行目标说明
- Done when: 已明确改动文件与无落点规则
- Verification: Medium todo 已同步
- Notes: 3.3/3.4/3.8 为主要代码落点

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 列出 Phase 3 所需依赖与验证约束
- Goal: 让执行与验证保持一致
- Inputs / Dependencies: typecheck / eslint / vitest / build、目标文件
- Procedure / Implementation notes: 保持最小改动，优先复用现有 `Promise.all` 与 route prefetch 结构
- Output / Artifact: 当前阶段依赖清单
- Done when: 提权需求与验证命令明确
- Verification: `PROJECT_EXECUTION_STATE.md` 已同步
- Notes: vitest / build 仍需可能提权

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化 server-prefetch 热点审计结论
- Goal: 对应真实服务端性能问题
- Inputs / Dependencies: `http.ts`、`serverFirstRoutePrefetch.ts`、相关 GET helper
- Procedure / Implementation notes:
  - 随机 `X-Request-Id` 会让同 URL/同 init 的 server GET 失去稳定缓存键
  - route prefetch 当前缺少共享 `React.cache()` wrapper
  - 现有 `Promise.all` 并行抓取已经覆盖 3.6 / 3.7 的主要要求
  - 当前无 server action，因此 3.1 无新增代码落点
- Output / Artifact: Phase 3 上下文图
- Done when: 每个目标项都能映射到具体文件
- Verification: 目标文件已审阅
- Notes: 不扩展到后端仓库与客户端数据层

### 2.2 Break the current phase into executable units
- [x] Task: 拆解 Phase 3 执行单元
- Goal: 保持可跟踪
- Inputs / Dependencies: baseline、目标文件
- Procedure / Implementation notes:
  - `http.ts` 增加 cache-friendly header 开关
  - 相关 GET helper 支持 server-only fetch 选项透传
  - 新增 `serverPrefetchCache.ts` 集中管理 cache policy 与 `React.cache()`
  - `serverFirstRoutePrefetch.ts` 替换为共享 wrapper
  - 跑 typecheck / eslint / vitest / build
- Output / Artifact: 可执行分解
- Done when: 每一步都有明确文件与验收点
- Verification: 3.x/4.x 已细化
- Notes: 优先复用现有数据结构与返回类型

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 处理 cache-friendly GET 与共享 server cache 基础设施
- Goal: 先建立稳定缓存键与共享 wrapper 基础
- Inputs / Dependencies:
  - `frontend/src/services/http.ts`
  - `frontend/src/services/chats.ts`
  - `frontend/src/services/knowledgeBases.ts`
  - `frontend/src/services/ingestionBatches.ts`
  - `frontend/src/services/bootstrapSubmissions.ts`
  - `frontend/src/services/serverPrefetchCache.ts`
- Procedure / Implementation notes:
  - 增加 `includeRequestIdHeader`
  - 让 GET helper 支持 server-only fetch 选项
  - 用模块级常量 hoist cache policy，并用 `React.cache()` 包装
- Output / Artifact: 稳定缓存键与共享 server cache 改动
- Done when: server-prefetch 可缓存 GET 不再默认带随机 request id header
- Verification: typecheck / eslint / http.test
- Notes:
  - 已完成 `http.ts` header 开关
  - 已完成相关 GET helper 透传选项
  - 已完成 `serverPrefetchCache.ts` 模块级包装

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 接入 route prefetch、保留并行抓取并完成验证
- Goal: 收口 Phase 3
- Inputs / Dependencies:
  - `frontend/src/services/serverFirstRoutePrefetch.ts`
  - targeted tests / build / typecheck
- Procedure / Implementation notes:
  - 将 route prefetch 默认实现切换到共享 wrapper
  - 保留已有 `Promise.all` 并行抓取结构
  - 运行验证并记录提权
- Output / Artifact: route prefetch 接线、验证结果、commit
- Done when: 默认 server-prefetch 路径已统一，验证完成
- Verification: routePrefetch.test / build / typecheck
- Notes:
  - 已完成 `serverFirstRoutePrefetch.ts` 接线
  - 3.6 / 3.7 无需额外代码，沿用现有并行抓取
  - 当前仅剩 git commit 动作

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 运行与 Phase 3 结论直接相关的验证
- Goal: 防止只改代码不验证 server-side 路径
- Inputs / Dependencies: 完成后的代码、typecheck / eslint / vitest / build
- Procedure / Implementation notes:
  - 跑 `npm run typecheck`
  - 跑定向 `eslint`
  - 跑定向 `vitest`
  - 跑 `npm run build`
- Output / Artifact: Phase 3 验证记录
- Done when: 验证足以支撑 server-side 优化结论
- Verification: 命令输出留痕
- Notes:
  - `npm run typecheck` 通过
  - `npx eslint src/services/http.ts src/services/http.test.ts src/services/chats.ts src/services/knowledgeBases.ts src/services/ingestionBatches.ts src/services/bootstrapSubmissions.ts src/services/serverPrefetchCache.ts src/services/serverFirstRoutePrefetch.ts` 通过
  - `npx vitest run src/services/http.test.ts src/services/routePrefetch.test.ts` 通过（require_escalated）
  - `npm run build` 通过（require_escalated）

### 4.2 Reconcile phase completion and prepare the next step
- [ ] Task: 更新状态、提交 Phase 3 commit，并准备切到 Phase 4
- Goal: 留下完整审计轨迹
- Inputs / Dependencies: 已验证改动、git 工作区
- Procedure / Implementation notes:
  - 更新 active planning files
  - 提交明确 commit
  - 归档 Phase 3 计划
- Output / Artifact: commit + 过渡决策
- Done when: Phase 3 commit 完成，Phase 4 入口明确
- Verification: `git log -1 --stat`
- Notes: 当前 planning files 已到完成态；提交当前 commit 后才可标记完成并刷新为 Phase 4
