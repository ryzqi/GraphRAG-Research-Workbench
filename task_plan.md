# 上下文优化实施任务计划

## 目标

- 以 [上下文优化方案.md](F:\毕设\code\上下文优化方案.md) 作为唯一实现规格，在 `backend` 中按方案逐点实施上下文预算优化。
- 严格遵循“每次只修改一个点、完成验证后单独提交、再进入下一个点”的节奏。

## 当前范围

- `P2-1 用 langmem 替换 KB Chat 自建记忆` 已完成并单独提交。
- `P2-3` 的 Anthropic provider 优化按用户最新要求跳过，不进入实现。
- `P2-4 上下文指标化评估` 已完成并单独提交。
- 当前处理下一个未完成点：`P2-5 PII & 安全`。
- 本点先做最小实现：
  - General Chat 与 Deep Research 顶层 agent 接入可配置 `PIIMiddleware`；
  - Chat / Research 导出链路补显式脱敏后处理；
  - 不把 KB Chat 自建图或其他未经过 agent middleware 的链路误报为已覆盖。
- 不在本点混入 `P2-3` 跳过项或其他后续任务，也不提交现有脏工作树中的用户改动。

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
| Phase 7 | complete | 取证并实施 `P2-4` 的最小上下文指标化评估 |
| Phase 8 | complete | 取证并实施 `P2-5` 的最小 PII 防护闭环 |

## 当前任务

- Active item: `全部任务已完成`
- Done condition:
  - `P2-5` 相关代码、测试、graphify 与控制面已单点收口。
  - 当前方案中的剩余实现点已全部完成或按用户要求明确跳过。

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
- `P2-5` 方案原文只给出 `PIIMiddleware` 片段，但当前仓库导出器不经过 agent middleware；若只接 agent middleware，会把“导出/发布场景”误写成已覆盖。
- `PIIMiddleware` 默认 `apply_to_input=True`、`apply_to_output=False`、`apply_to_tool_results=False`；若不显式配置，会偏离“对外输出脱敏”的目标。
- Chat 导出包含会话消息、阶段摘要与证据详情；Research 导出直接把 `report_md` 写成 PDF。若导出脱敏做得过重，可能破坏结构；若做得过轻，又会留下真实敏感信息。
