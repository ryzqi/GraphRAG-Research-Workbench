# 上下文优化实施任务计划

## 目标

- 以 [上下文优化方案.md](F:\毕设\code\上下文优化方案.md) 作为唯一实现规格，在 `backend` 中按方案逐点实施上下文预算优化。
- 严格遵循“每次只修改一个点、完成验证后单独提交、再进入下一个点”的节奏。

## 当前范围

- `P2-1 用 langmem 替换 KB Chat 自建记忆` 已完成并单独提交。
- `P2-3` 的 Anthropic provider 优化按用户最新要求跳过，不进入实现。
- 当前处理下一个未完成点：`P2-4 上下文指标化评估`。
- 本点先做最小实现：把可由当前代码真实计算的上下文指标补入 `ContextBuilder.build_metrics` 与相关 `stage_summaries`，不在本点扩展远端平台、Grafana、论文或 Claude provider 专属指标。
- 不在本点混入 `P2-5`，也不提交现有脏工作树中的用户改动。

## 约束

- 先读代码、再做网络调研、再写代码。
- 生产代码修改前必须先建立可失败的验证路径；若缺少现成测试，则至少先跑能暴露当前行为的定向验证。
- 修改 backend 代码后，需要按仓库规范重建 `backend/graphify-out/` 图谱。
- 提交必须只包含当前点相关改动。

## 事实源

- 实现规格：`F:\毕设\code\上下文优化方案.md`
- 项目规则：`F:\毕设\code\AGENTS.md`
- backend 图谱：`F:\毕设\code\backend\graphify-out\GRAPH_REPORT.md`
- 当前源码与测试
- 官方文档/官方最佳实践页面（仅用于本轮调研记录，不替代本地事实源）

## 分阶段

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| Phase 1 | complete | 初始化控制面，确认规格、代码范围、工作树状态 |
| Phase 2 | complete | 取证 `P2-1` 的 KB Chat 记忆读写链路、LangMem API 与最小迁移边界 |
| Phase 3 | complete | 按 TDD 实施 `P2-1` 的 LangMem 记忆读写迁移 |
| Phase 4 | complete | 运行验证、代码审查、重建 backend graphify |
| Phase 5 | complete | 创建 `P2-1` 单独 git 提交并记录下一步 |
| Phase 6 | complete | 调研并重定义 `P2-3` 的实现边界，确认 Anthropic provider 优化跳过 |
| Phase 7 | in_progress | 取证并实施 `P2-4` 的最小上下文指标化评估 |

## 当前任务

- Active item: `P2-4 上下文指标化评估`
- Done condition:
  - `ContextBuilder.build_metrics()` 能产出当前代码可真实计算的上下文指标，至少覆盖 `context_utilization`、`truncation_rate` 和可由 budgets/usage 推导的预算利用率。
  - KB Chat 的 `merge_context` / `memory` 路径补充 `memory_recall_precision` 所需的最小本地指标基础，至少能记录 memory 命中条数、渲染条数、去重后保留条数。
  - General Chat / KB Chat 现有 `run.metrics` 与 `run.stage_summaries` 不被破坏，并新增测试覆盖。
  - 完成单独验证和单独提交，不混入 `P2-5` 或跳过项 `P2-3`。

## 已知风险

- 工作树当前已有用户未提交改动：`docs/api_contract_research.md`、`docs/architecture.md` 删除，`上下文优化方案.md` 未跟踪；本轮不得覆盖。
- 方案中的文件路径、字段名和实现点需要以当前 checkout 实际代码为准，不能直接照抄方案文字。
- `P0-1` 已通过单独提交 `01c6705` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P0-2` 已通过单独提交 `867dcaf` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P0-3` 已通过单独提交 `e0d84d0` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P0-4` 已通过单独提交 `d199613` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P0-5` 已通过单独提交 `4f21685` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P0-6` 已通过单独提交 `aaf0b83` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P1-1` 已通过单独提交 `d78f9d1` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P1-2` 已通过单独提交 `faee007` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P1-3` 已通过单独提交 `019ebe5` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P1-4` 已通过单独提交 `bc57ebb` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P1-5` 已通过单独提交 `fbd7771` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- `P1-6` 已通过单独提交 `1465196` 落地；下一步必须从该提交后的工作树继续，避免把新点混入已完成提交。
- 当前 Deep Agents 已内置 `FilesystemMiddleware`；若误按方案再叠一层 `FilesystemFileSearchMiddleware`，会重复暴露工具面且不能解决 `StateBackend` 对未预置文件不可见的问题。
- `StateBackend` 明确要求预置文件必须通过 `invoke({"files": ...})` 进入状态；若直接把非 priority 文件从 `request["files"]` 删除，而没有补 seed/fallback backend，runtime 将无法按需读取这些文件。
- `P2-4` 方案原文包含 LangSmith tracing dataset、Grafana/日志面板、prompt_cache_hit_rate、tool_selection_drop_rate 等大范围指标；当前仓库并无现成 LangSmith 接入与 selector drop 埋点，若不收紧边界，容易把一个点膨胀成跨系统工程。
