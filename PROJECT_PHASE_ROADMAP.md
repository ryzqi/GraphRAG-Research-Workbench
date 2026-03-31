# Project Phase Roadmap

## Project Context
- Project Name: frontend-react-performance-optimization
- Project Mode: Multi-phase
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Primary User / Stakeholder: 当前仓库前端维护者
- Customer Problem / Desired Outcome: 在不改变视觉风格、配色与交互设计语言的前提下，系统性消除前端性能热点，降低首屏阻塞、缩小 bundle、减少不必要重渲染与运行时开销。
- Why Now / Decision Driver: 用户明确要求按 Vercel React Best Practices 分大类逐项落地，并要求每个大类完成后独立提交，形成可审计演进历史。
- Overall Goal: 依照 8 个性能类别依次完成前端性能优化，每个类别都保留“代码改动 + 直接验证 + 独立 git 提交”证据链。
- Current Active Phase: Phase 3 - Server-Side Performance
- Overall Success Criteria:
  - 8 个大类别全部按顺序完成，中间不跳类、不混类。
  - 每个类别仅做性能相关优化，不改视觉风格、配色或产品设计。
  - 每个类别完成后都有 fresh verification，并完成一次 git commit。
  - 所有变更保持前端可构建、可类型检查，关键改动具备最小可验证证据。
- Non-goals:
  - 不做视觉重设计、配色调整、文案改版。
  - 不做与当前性能目标无关的顺手重构。
  - 不为旧实现保留兼容层或双轨逻辑，除非该类别本身明确需要。
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Overall Evaluation Objective: 以“代码路径消除性能反模式 + 前端验证通过”为主，逐阶段收敛。
- Overall Metric / Rubric:
  - 代码审计确认目标反模式被消除或显著减少。
  - `npm run typecheck` 通过。
  - 与当前类别直接相关的 targeted tests / targeted lint / build 通过；若受沙箱限制阻断，需明确记录。
- Overall Pass Threshold / Stop Condition: 当前类别的目标反模式处理完成，且存在对应验证证据后，才允许进入下一类别。
- Key Constraints:
  - 仅优化性能，不改风格、配色、整体设计。
  - 一次只执行一个大类别。
  - 每完成一个大类别后必须 git commit。
  - 环境为 Windows + PowerShell；验证受当前沙箱对 spawn 的限制影响。
- Key Risks / Unknowns:
  - `next build`、`npm run analyze` 与默认 `vitest run` 在沙箱中可能存在 `spawn EPERM` 风险。
  - 某些优化可能跨 server/client 边界，需要分阶段保持最小改动。
- Parked / Deferred Threads:
  - 若某类别需要更重的性能基准工具，再按需引入，不预先扩项。
- Last Updated: 2026-03-31

## Module Map
- Module / Domain 1: `frontend/src/app`
  - Responsibility: App Router 路由入口、服务端预取、首屏加载路径
  - Key dependencies: `frontend/src/services/serverFirstRoutePrefetch.ts`, `frontend/src/components/providers/*`
  - Notes: Phase 1、3、6 的关键入口
- Module / Domain 2: `frontend/src/views`
  - Responsibility: 页面级 client 组件与交互编排
  - Key dependencies: `frontend/src/hooks/*`, `frontend/src/components/*`
  - Notes: Phase 2、4、5、6 的主要改动面
- Module / Domain 3: `frontend/src/components`
  - Responsibility: 可复用 UI / Chat / Research / Shell 组件
  - Key dependencies: MUI、React、Next dynamic/lazy
  - Notes: Phase 2、5、6、8 的主要改动面
- Module / Domain 4: `frontend/src/hooks` + `frontend/src/services`
  - Responsibility: 数据获取、SWR、流式会话控制、纯函数工具
  - Key dependencies: `swr`, `fetch`, route prefetch helpers
  - Notes: Phase 3、4、7 的主要改动面
- Module / Domain 5: `frontend/src/theme`
  - Responsibility: 主题定义与 provider 装配
  - Key dependencies: MUI theme system
  - Notes: Phase 2 的 barrel import 热点

## Phase Roadmap
### Phase 1: Eliminating Waterfalls
- Status: Completed
- Objective: 清除路由级和关键加载链路中的明显 waterfall，优先优化首屏阻塞路径。
- Scope Boundary: 仅覆盖 1.1~1.5；重点是 App Router 首屏预取与 Suspense 边界，不碰 bundle 与重渲染类改动。
- Modules Involved: `src/app`, `src/components/providers`, `src/services`
- Main Deliverables: route prefetch 解耦、延迟 await、并行化与 Suspense 边界落地、验证与 commit
- Entry Conditions: 当前前端基线已完成初步审计；`npm run typecheck` 可运行
- Completion Conditions: 当前可识别的首屏 waterfall 处理完成，验证通过并完成 commit
- Transition Notes: 已完成并提交 `8e7e152`，切换至 Phase 2

### Phase 2: Bundle Size Optimization
- Status: Completed
- Objective: 压缩不必要的初始 bundle，处理 barrel import、重模块与用户意图预加载。
- Scope Boundary: 仅覆盖 2.1~2.5
- Modules Involved: `src/theme`, `src/views`, `src/components`, `src/app`, `next.config.mjs`
- Main Deliverables: bundle 热点代码分拆、动态加载、按需预取、第三方延后
- Entry Conditions: Phase 1 已提交
- Completion Conditions: 相关 bundle 反模式处理完成、验证完成并提交
- Transition Notes: 已完成并提交 `7f5eee0`，并归档到 `archive/perf-phases/*.phase-02-bundle-size.md`

### Phase 3: Server-Side Performance
- Status: Active
- Objective: 优化 RSC / server-side 数据路径、缓存与序列化边界。
- Scope Boundary: 仅覆盖 3.1~3.9；本轮实际落点聚焦 3.3、3.4、3.8，并确认 3.1/3.2/3.5/3.9 当前无新增代码改动必要，3.6/3.7 继续沿用既有并行抓取。
- Modules Involved: `src/app`, `src/services`, `src/lib`
- Main Deliverables: cache-friendly GET、共享 server prefetch cache、请求内去重、验证与 commit
- Entry Conditions: Phase 2 已提交
- Completion Conditions: server-side 热点处理完成并提交
- Transition Notes: 完成后转入客户端数据获取阶段

### Phase 4: Client-Side Data Fetching
- Status: Pending
- Objective: 优化全局事件监听、SWR 去重与 localStorage 使用。
- Scope Boundary: 仅覆盖 4.1~4.4
- Modules Involved: `src/hooks`, `src/lib`, `src/views`, `src/components`
- Main Deliverables: 客户端数据读取路径减噪与去重
- Entry Conditions: Phase 3 已提交
- Completion Conditions: client data fetching 热点处理完成并提交
- Transition Notes: 转入重渲染优化阶段

### Phase 5: Re-render Optimization
- Status: Pending
- Objective: 清理无效 memo/effect/state 订阅，降低不必要重渲染。
- Scope Boundary: 仅覆盖 5.1~5.15
- Modules Involved: `src/views`, `src/components`, `src/hooks`
- Main Deliverables: 关键页面与组件的重渲染路径收敛
- Entry Conditions: Phase 4 已提交
- Completion Conditions: rerender 反模式处理完成并提交
- Transition Notes: 转入渲染性能阶段

### Phase 6: Rendering Performance
- Status: Pending
- Objective: 优化 hydration、条件渲染、脚本加载与长列表显示策略。
- Scope Boundary: 仅覆盖 6.1~6.11
- Modules Involved: `src/app`, `src/components`, `src/views`
- Main Deliverables: 渲染层热点优化与验证
- Entry Conditions: Phase 5 已提交
- Completion Conditions: rendering 反模式处理完成并提交
- Transition Notes: 转入 JS 运行时优化阶段

### Phase 7: JavaScript Performance
- Status: Pending
- Objective: 收敛循环、查找、缓存与空闲调度等低中优先级热点。
- Scope Boundary: 仅覆盖 7.1~7.14
- Modules Involved: `src/services`, `src/hooks`, `src/lib`, `src/views`
- Main Deliverables: JS 微观性能反模式收敛
- Entry Conditions: Phase 6 已提交
- Completion Conditions: JS 性能项完成并提交
- Transition Notes: 转入高级模式阶段

### Phase 8: Advanced Patterns
- Status: Pending
- Objective: 补齐初始化、事件处理与稳定引用类高级模式。
- Scope Boundary: 仅覆盖 8.1~8.3
- Modules Involved: `src/providers`, `src/hooks`, `src/views`
- Main Deliverables: 高级性能模式收口、最终验证、最终提交
- Entry Conditions: Phase 7 已提交
- Completion Conditions: 高级模式项完成并提交，项目收尾
- Transition Notes: 汇总全链路验证与剩余风险

## Phase History / Change Log
- 2026-03-31:
  - What changed: 初始化多阶段路线图，并将 Phase 1 设为当前活动阶段
  - Why it changed: 用户要求按类别分批执行并逐类提交
  - Impact on current or future phases: 后续每一类完成后都需要刷新 active todo 并归档上一阶段
- 2026-03-31:
  - What changed: Phase 1 完成并提交 `8e7e152`；当前活动阶段切换到 Phase 2
  - Why it changed: 已满足首屏 waterfall 类别的完成条件
  - Impact on current or future phases: 当前开始处理 bundle 体积相关热点
- 2026-03-31:
  - What changed: Phase 2 完成并提交 `7f5eee0`；当前活动阶段切换到 Phase 3
  - Why it changed: 已满足 bundle 类别的完成条件
  - Impact on current or future phases: 当前开始处理 server prefetch、缓存与序列化边界
- 2026-03-31:
  - What changed: Phase 3 已完成代码与验证收口，当前待提交独立 commit
  - Why it changed: 已满足 cache-friendly GET、共享 server prefetch cache 与 React.cache 去重的阶段目标
  - Impact on current or future phases: 提交后可切换到 Phase 4，不再回流扩项服务端预取链路

## Archive References
- Phase archive path(s): `archive/perf-phases/`
- Notes about where historical phase todos, state snapshots, or verification artifacts were stored:
  - Phase 1: `*.phase-01-waterfalls.md`
  - Phase 2: `*.phase-02-bundle-size.md`
