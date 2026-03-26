# 基于外部研究与最新 Deep Agents 用法的本仓库落地分析（2026-03-26）

## 一、问题重述

当前 `full-refactor-deep-research` 的核心目标不是“做一个能跑的 demo 研究代理”，而是：

- 对接当前仓库的公开 API / 前端服务 / Worker / DB
- 形成单一路径的 research session 契约
- 在生产约束下支持 planning、long-running research、interrupt / resume、artifacts、observability、gate

因此，我们要找的不是“最强研究算法”，而是 **对当前仓库最稳、最可维护、最少自研 orchestration 的实现骨架**。

## 二、推荐总方案

### 推荐方案：`业务壳层 + Deep Agents runtime + deterministic finalizer/service glue`

```
API / Worker / DB / SSE / Audit / Gate
  └── ResearchService (deterministic shell)
        ├── PreflightPlanner (lightweight, non-Deep-Agents or thin agent usage)
        ├── DeepResearchRuntime (create_deep_agent single entry)
        └── ResearchFinalizer (deterministic schema + artifact writer)
```

### 为什么推荐这个方案

1. **符合外部最佳实践**  
   外部高质量系统几乎都显式分 `scope/planning`、`research runtime`、`report writing/finalization`。

2. **符合 Deep Agents 的天然优势边界**  
   Deep Agents 强在 long-running tool loop、file context、subagents、streaming、HITL、memory / skills，而不是业务数据库状态机。

3. **符合本仓库事实源约束**  
   我们已经有 FastAPI / Celery / SQLAlchemy / PostgreSQL / frontend service；因此更适合把 Deep Agents 夹在中间，而不是反过来改造整个产品结构去适配 agent。

## 三、分层建议

### A. Preflight Planner：轻、显式、可审查

**职责：**
- 澄清问题边界
- 生成 research brief
- 生成子任务与 `target_sources`
- 估算 complexity / budget / confirmation_required

**不做：**
- 大规模外部检索
- 真正长时研究
- citation 对齐

**原因：**
- 外部最佳实践表明，planner 的价值是固定研究北极星，而不是抢 runtime 的活。
- Planner 太重会导致“先造第二套 runtime，再把事情做两遍”。

### B. DeepResearchRuntime：唯一 agentic 入口

**职责：**
- 按 plan snapshot 执行研究
- 决定何时直接查、何时下发 subagent
- 周期性压缩上下文并沉淀 interim findings
- 产生 source bundles / structured findings

**约束：**
- 只能有一个 `create_deep_agent` runtime 入口
- 不引入 MCP 工具到研究模式
- 不承担业务级 DB 状态机

### C. Finalizer：确定性收口层

**职责：**
- canonical citation 对齐
- `report_json` schema 校验
- `report_md` 生成
- 双工件持久化

**原因：**
- `node-DeepResearch`、Jina、Egnyte 等都提醒我们：搜索 / 推理循环与长文报告生成不是同一问题。
- finalizer 独立后，质量诊断与回放会清楚很多。

## 四、Deep Agents 在本仓库中的具体使用建议

### 1. runtime harness 结构

**主代理（lead agent）**
- 使用较强模型
- 负责读取 brief、决定 source routing、创建 todo、委派 subagents、收敛 findings

**子代理（workers）**
- 默认优先 general-purpose
- 只有确有边界差异时才专门化：`kb`、`web`、`paper`、`citation`
- 可以显式使用较便宜的 `subagent_model`

**关键原因：**
- Anthropic 证明了 breadth-first research 对 parallel workers 特别受益。
- Onyx 也提醒：大多数生产系统不该超过 2 层代理深度。

### 2. backend 路由

**推荐：** `CompositeBackend`

| 路径 | 后端 | 用途 |
| --- | --- | --- |
| `/workspace/` | `StateBackend` | 当前任务输入上下文 |
| `/scratch/` | `StateBackend` | 网页摘录、临时笔记、中间总结 |
| `/plans/` | `StateBackend` | brief / plan snapshot / source bundle 草稿 |
| `/memories/` | `StoreBackend` | 持久记忆、固定规范 |
| `/skills/` | `StoreBackend` | source-specific workflows |

**不要做：**
- 直接把业务事实写到 agent backend
- 用单一 FilesystemBackend 混装所有临时态和长期态

### 3. skills / memory 设计

**memory（最小强约束）**
- 研究模式禁止 MCP
- source routing 原则
- citation / evidence 纪律
- 安全边界

**skills（按需加载）**
- `kb-research`
- `web-research`
- `paper-research`
- `citation-finalization`

**理由：**
- 官方 docs 明确建议 memory 保持精简，skills 用 progressive disclosure。
- 这与我们现有 AGENTS / skills 工作方式高度一致。

### 4. streaming 设计

Deep Agents 官方 streaming 文档给出的关键能力，是 `subgraphs=True` 后每个事件都带 namespace。

**因此推荐：**

SSE 事件至少包含：
- `session_id`
- `event_id`
- `sequence`
- `phase`
- `event_type`
- `namespace`
- `subagent_name`（可从 namespace 映射）
- `payload`

**UI 层应做到：**
- main agent 显示 phase 进度
- subagent timeline 单独显示
- tool / token / result 流可以按 namespace 聚合

### 5. interrupt / resume 设计

**Deep Agents 层：**
- 仅对危险工具使用 `interrupt_on`
- 使用稳定 `thread_id`
- 使用同一 `checkpointer`

**业务层：**
- 保留 plan confirm / user interrupt / resume API
- 把审批、拒绝、恢复写入 research events

**结论：**
- tool-level HITL 与 business-level interrupt/resume 是两层能力，不能混为一谈。

## 五、与当前提案相比，建议新增的设计收口

### 新增收口 1：把 `research brief` 升级为 planner 的正式产物

当前提案已有 `plan snapshot`，但还不够强调 brief 的价值。建议把 planner 输出固定为：

- `research_brief`
- `complexity`
- `subtasks`
- `target_sources`
- `budget_hint`
- `confirmation_required`

### 新增收口 2：runtime 明确有 `source bundle / interim summary`

finalizer 之前，runtime 应先沉淀：

- `interim_findings`
- `source_bundles`
- `coverage_gaps`
- `next_actions`（如果中断 / 继续）

这样恢复、评测、回放才有抓手。

### 新增收口 3：前端工作台以 namespace-aware timeline 为核心

不是只展示“助手正在研究”，而是：

- 现在在哪个 phase
- 哪个 subagent 在查什么
- 查到了哪些 source bundle
- 当前是等待确认、继续研究、还是进入 finalizer

### 新增收口 4：用主 / 子代理模型分层控制成本

推荐：
- lead agent：强模型
- subagents：更便宜但稳定的模型
- finalizer：结构化输出能力强的模型

这样成本门禁才可真正执行，而不是靠笼统 token 限额。

## 六、建议更新到当前提案中的关键文字

1. **把 `checkpointer` 写成 runtime 必备基础设施，而非“需要 HITL 时再加”。**
2. **把 `subgraphs=True` / `namespace` streaming 写入 API / frontend 契约。**
3. **把 `memory vs skills` 分层写入 design defaults。**
4. **把 `subagent_model` / model split 写入成本治理策略。**
5. **把 `research brief`、`source bundle`、`interim summary` 写入 artifacts / schema 设计。**

## 七、最终建议

**推荐继续沿用当前提案的大方向**，但要把它从“正确方向的架构草案”进一步收紧为“符合最新 Deep Agents 能力边界的生产设计”：

- planner 更轻，但输出更正式
- runtime 更像 harness，而不是第二套业务系统
- streaming 更强调 namespace / subagent visibility
- memory / skills / backend 路由更显式
- finalizer 更确定性
- gates 更贴近真实开放式研究任务

换句话说：

> 本仓库不应去“复刻一个 Anthropic / OpenAI 式全栈研究平台”，而应把 Deep Agents 作为研究执行内核，外面包一层非常清楚的业务壳层，把 session / event / artifact / audit / gate 这些确定性职责抓牢。

## 八、参考链接

- 外部调研汇总：`research-landscape-2026-03-26.md`
- Deep Agents 最新用法：`deepagents-latest-usage-2026-03-26.md`
