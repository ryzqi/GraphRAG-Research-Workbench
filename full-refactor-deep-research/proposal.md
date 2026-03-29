## Why

当前代码库已经删除旧深度研究实现，因此这份方案直接定义一条面向当前仓库的深度研究主路径：直接接入现有公开端点集合、现有前端研究服务文件和现有后端路由组织方式。

新的研究主路径必须同时满足生产级约束：先计划再执行、来源感知路由、可恢复事件流、双产物输出、可观测、可评测、可审计、可回滚。

同时，研究系统不应在业务层重写 DeepAgents 已内建的 orchestration 能力。本方案明确把 planning、context offloading、subagent isolation、skills、memory、HITL、sandbox 等能力交给 DeepAgents harness；业务层只保留会话、事件、工件、SSE、幂等、审计与门禁等确定性壳层。

本提案已结合 2026-03-26 的外部调研与官方 Deep Agents 文档刷新：`research-landscape-2026-03-26.md`、`deepagents-latest-usage-2026-03-26.md`、`deepagents-implementation-analysis-2026-03-26.md`。

本轮提案进一步收紧外部搜索策略：深度研究模式下同时启用 **Tavily、Jina Reader、SearXNG、arXiv** 四条检索能力，其中 Tavily 保留并启用 `search/extract/crawl/research` 全功能；Jina Reader 仅提供 `r.jina.ai` 页面读取；SearXNG 提供可控 metasearch；论文检索固定走 direct arXiv。

## Goals / Non-Goals

### Goals
- 将深度研究直接集成到当前公开端点集合（当前挂载于 `backend/src/app/api/v1/api.py`）。
- 将研究运行模型统一为 `session_id` 驱动：创建、计划确认、事件流、中断恢复、工件读取都围绕 `session_id`。
- 将研究前置阶段收敛为独立的 **preflight planner**：先产出 `research_brief`、复杂度、子任务、`target_sources`、预算提示，再决定是否进入长时研究。
- 将正式研究执行统一到 `create_deep_agent` 单入口，并最大化复用 DeepAgents 默认 harness 能力。
- 将外部研究收敛为 `kb | web | paper | hybrid` 四类来源路由；网页研究同时启用 Tavily 全功能、Jina Reader、SearXNG，论文检索走 Python `arxiv` 库。
- 将 citation/report 收口为显式 finalizer 阶段，稳定产出 `report_md` 与 `report_json`。
- 建立 `research_sessions / research_events / research_artifacts` 三表主路径，支持恢复、回放、审计。
- 建立质量 / 延迟 / 成本 / 韧性门禁，并覆盖纯网页、纯论文、混合来源三类任务。

### Non-Goals
- 不改变 KB Chat、General Chat、评测链路的业务语义与对外契约。
- 不引入研究模块的 MCP 工具扩展；研究模式继续禁用 MCP。
- 不接入 Google Scholar、Semantic Scholar、Crossref 等额外学术搜索供应商；学术外部搜索首期仅覆盖 arXiv。
- 不进行跨服务拆分（继续保持 FastAPI + Celery 单体部署）。

## Scope & Integration Policy

- **范围只覆盖 Research 域**：planner、runtime、持久化、导出、前端工作台、观测与门禁。
- **直接接入当前端点集合**：研究接口直接落到当前公开 API 命名空间。
- **直接改造当前前端服务文件**：`frontend/src/services/research.ts` 直接收敛为新的会话化研究服务。
- **单一路径原则**：研究域统一使用 `session_id`、单一 SSE 事件协议、单一工件读取路径。
- **搜索提供方策略**：深度研究 runtime 内同时装配 Tavily、Jina Reader、SearXNG、arXiv；不做“全局二选一”的单 provider 设计。
- **数据策略**：新研究会话只写 `research_sessions`、`research_events`、`research_artifacts` 三表。
- **Runtime/业务边界**：DB 三表与 API 壳层是唯一业务事实源；Deep Agents backend 仅用于上下文、skills、memory 与中间工件处理。

## Execution Shape

本次变更的主路径收敛为以下 7 步：

1. **create session**：客户端创建研究会话，获得 `session_id`。
2. **preflight planner**：轻量规划阶段先产出 `research_brief` 与 `plan snapshot`，包含复杂度、子任务、`target_sources` 与预算提示。
3. **plan confirmation**：交互式场景可确认/调整计划；自动化场景可策略化 auto-approve。
4. **deep research runtime**：已审批计划交给 `DeepResearchRuntime` 执行，主代理按需要委派 `general-purpose` 或少量 source-specialized subagents；网页任务可在 Tavily / Jina Reader / SearXNG 之间按策略组合调用，论文任务固定走 arXiv，并阶段性沉淀带 `source_provider` 的 `source_bundle`、`interim_summary`、`coverage_gaps`。
5. **citation/report finalizer**：研究结果进入显式 finalization 阶段，完成 canonical citations、结构化输出和可读报告生成。
6. **streaming + resume**：全过程通过标准 SSE 事件流输出，并支持 `Last-Event-ID` / `resume_from_event_id` 恢复；研究 runtime 流需保留 subgraph `namespace`。
7. **dual artifacts**：最终稳定落盘 `report_md` 与 `report_json`，统一供前端、导出与审计读取。

## What Changes

- 将“计划确认”从主研究执行中前移为独立 **preflight planner** 阶段，而不是把高成本研究直接嵌入主 loop。
- 将 DeepAgents 明确定位为 **研究 harness**：优先复用 TodoList、Filesystem、SubAgent、Summarization、PatchToolCalls、Skills、Memory、HITL、Sandbox 等内建能力。
- 主研究阶段默认使用 `general-purpose` 子代理做上下文隔离；仅为 `kb`、`web`、`paper`、`citation` 等明显 specialization 场景引入少量自定义子代理。
- 将 source routing 从“标签字段”提升为“工具集与子代理边界”：`paper` 任务优先 direct arXiv；`web` 任务同时可用 Tavily、Jina Reader、SearXNG；`hybrid` 任务先建论文基线，再通过多 provider 网页检索做补证。
- 保留并启用 Tavily `search/extract/crawl/research` 全功能，而不是只开放单一 `search` 能力。
- 引入 Jina Reader 页面读取能力：`r.jina.ai` 负责对目标 URL 做标准化读取、流式读取与难读页面兜底。
- 引入 SearXNG 作为可控 metasearch provider，通过受控实例的 Search API 提供多引擎聚合、类别/时间范围/引擎筛选与低锁定成本的网页搜索能力。
- 将 citation/report 处理拆成独立 finalizer，而不是让主研究阶段同时承担资料搜集与最终引用对齐。
- 将 `response_format` 放到最终产物生成阶段，由 finalizer 负责产出 `report_json`，避免主研究阶段长期背负强 schema 约束。
- 将文件后端明确限制为 agent 上下文管理用途：`CompositeBackend` 路由 `/workspace|/scratch|/plans -> StateBackend`，`/memories|/skills -> StoreBackend`；业务事实仍以数据库三表为唯一事实源。
- 将 `checkpointer` 明确为 runtime 标配基础设施；保持 `thread_id <-> session_id` 稳定映射，为恢复与 HITL 提供底座。
- 将流式协议升级为 **namespace-aware SSE**：前端不仅消费文本，还要消费 `phase`、`namespace`、`subagent_name`、`event_type`、`payload`。
- 将 canonical citation 从“只分来源类型”提升为“来源类型 + 检索提供方 + 原始 URL”：至少保留 `source_type`、`source_provider`、`retrieval_method`、`origin_url`，避免 Jina/SearXNG/Tavily 中转信息污染最终引用。
- 若研究需要执行命令，统一通过官方 sandbox backend 提供 `execute`；生产研究链路不使用 `LocalShellBackend`。
- 业务层仅保留确定性职责：会话创建、计划审批状态、事件落库、SSE 映射、幂等恢复、工件更新、审计与门禁。

## Capabilities

### New Capabilities
- `research-runtime`: DeepAgents 单引擎运行时，含 preflight planner、source-aware routing、DeepAgents harness、中断恢复、预算治理、citation/report finalizer。
- `research-persistence-model`: 会话 / 事件 / 工件三类数据模型与并发幂等约束。
- `research-api-streaming`: 当前公开端点集合下的研究会话 API 与 SSE 事件协议。
- `research-export-artifacts`: 基于工件表的 Markdown + JSON 双产物导出与结构化失败语义。
- `research-frontend-workbench`: 当前前端研究服务与事件驱动工作台。
- `research-current-integration`: 与现有路由、现有前端服务文件、现有测试基线的单路径集成能力。
- `research-observability-evaluation`: 研究链路可观测、评测、门禁与回滚能力。

### Modified Capabilities
- （无。当前按新增能力定义。）

## Impact

- **Backend**：新增 planner、runtime、service、router、store、finalizer、测试；直接接入当前 API 路由集合，并新增 Tavily / Jina Reader / SearXNG / arXiv 适配与路由策略。
- **Database**：新增 `research_sessions`、`research_events`、`research_artifacts` 表与对应约束。
- **Frontend**：直接改造 `frontend/src/services/research.ts`、研究 hooks 与研究页，改成 session-based 事件驱动工作台，并消费 namespace-aware SSE。
- **API/Contract**：公开研究契约直接落到当前端点集合。
- **Observability/Eval**：补齐 trace、metrics、gate、fault injection、replay、rollback。
- **Docs/Ops/QA**：更新架构文档、演示脚本、SLO、回滚手册与当前研究契约文档。

## Acceptance Criteria (Definition of Done)

### Contract & Data
- 当前公开端点集合中存在可用的研究会话创建 / 计划确认 / 事件流 / 中断 / 恢复 / 工件读取接口，且返回 `session_id` 驱动的契约。
- `research_sessions`、`research_events`、`research_artifacts` 三表完成落地，并满足 `(session_id, sequence)`、`(session_id, event_id)` 等唯一约束。
- `plan snapshot` 可按 `session_id` 持久化回放，至少包含 `research_brief`、子任务、`target_sources`、复杂度与预算提示。
- 文档、接口、导出和前端状态统一使用当前单路径术语。

### Runtime & Artifacts
- 研究运行时仅存在 `create_deep_agent` 单入口。
- runtime 配置中明确存在 `checkpointer`，并保持 `thread_id` 与 `session_id` 的稳定关联。
- 主代理与子代理模型分层配置可独立治理成本与并发；Deep Agents 落地时通过 `subagents[*].model` 显式声明，不能假设 `create_deep_agent` 存在顶层 `subagent_model` 参数。
- preflight planner 与正式研究执行分离，未审批计划不得直接进入高成本外部研究。
- 深度研究工具集内必须同时启用 Tavily、Jina Reader、SearXNG、arXiv 四条能力链路；不得在运行时裁剪为单 provider 模式。
- Tavily 在深度研究模式下必须开放 `search`、`extract`、`crawl`、`research` 全功能。
- `web` 任务必须可按策略调用 Jina Reader `r.jina.ai` 与 SearXNG Search API；Jina / SearXNG 返回的结果最终引用必须回写原始网页 URL。
- `paper` 任务必须通过 Python `arxiv` 库执行 direct arXiv 检索，不得退化为 Tavily 域名过滤。
- runtime 在 finalizer 前显式沉淀 `source_bundle`、`interim_summary`、`coverage_gaps`，供恢复、回放与诊断使用。
- 研究 finalizer 稳定产出 `report_md` 与 `report_json`，后者包含 canonical citations、`source_provider` / `retrieval_method` 元数据与论文结构化元数据。
- Task 11 后研究工件稳定补充 `metrics_snapshot` 与 `gate_snapshot`，用于发布门禁、事件回放诊断与 rollback 审计。
- 研究模式工具集不包含 MCP 注入工具；执行能力若存在，仅经 sandbox backend 暴露。

### Frontend UX
- 当前研究服务文件直接对接新研究契约。
- 工作台支持计划预览、来源路由展示、事件时间线、断线重连、去重重排、中断决策与双工件展示。
- 工作台能区分主代理与子代理事件流，并根据 `namespace` 展示子代理研究进度。
- 工作台能区分网页证据与论文证据，并进一步展示 Tavily / Jina Reader / SearXNG / arXiv provider 信息，同时安全渲染 Markdown / JSON 工件。

### Release Gates
- 发布流程输出质量 / 延迟 / 成本门禁报告；任一违约时自动阻断。
- 评测至少覆盖纯网页、纯论文、网页+论文混合三类任务。
- 纯网页评测中至少覆盖 Tavily 主路径、Jina Reader 参与路径、SearXNG 参与路径三类样本；混合来源评测需覆盖 `paper + web` 组合。
- 故障注入、事件回放、中断恢复与回滚演练全部通过。
- 文档、任务清单与规格统一使用当前研究单路径术语。

## Risks / Mitigations

- **风险：planner 与 runtime 边界不清，导致计划阶段重新自建一套 agent orchestration。**  
  缓解：planner 只产出 brief / 计划快照与预算信号，不承担正式研究执行。
- **风险：业务层重复实现 DeepAgents 已有能力。**  
  缓解：业务层只保留会话 / 事件 / 工件 / SSE / 幂等 / 审计；planning、subagents、offloading、skills、memory 由 DeepAgents 负责。
- **风险：source-aware 只有标签没有行为差异。**  
  缓解：通过 source-specialized tools / subagents 强化边界，而不是只写事件字段。
- **风险：多 provider 并启后引用链路被中转 URL 污染。**  
  缓解：canonical citation 强制保留 `origin_url` 与 `source_provider`，Jina/SearXNG/Tavily 中间 URL 不作为最终引用主键。
- **风险：SearXNG 公共实例格式能力不稳定，JSON/引擎集合可能被禁用。**  
  缓解：设计上要求使用受控实例或预先验证可用实例，禁止把公共匿名实例当生产唯一事实源。
- **风险：citation 对齐污染主研究阶段。**  
  缓解：拆出 citation/report finalizer 独立收口。
- **风险：前端数据层与当前契约漂移。**  
  缓解：直接改造 `frontend/src/services/research.ts` 并以当前研究会话契约为唯一入口。
- **风险：memory / skills 混用导致 prompt 膨胀。**  
  缓解：memory 只保留最小强约束，详细流程全部走 skills progressive disclosure。
- **风险：执行命令能力泄露到宿主机。**  
  缓解：执行能力只允许通过官方 sandbox backend 暴露。
- **风险：DeepAgents minor 升级造成行为漂移。**  
  缓解：按 pre-1.0 依赖治理，锁定 minor 版本并强制兼容回归。

## Rollout / Rollback

- **Rollout**
  1. 先落地三表模型、事件契约与 preflight planner。
  2. 落地 DeepResearchRuntime、source-aware tools/subagents 与 finalizer。
  3. 将当前公开端点与当前前端研究服务直接切到 session-based 契约。
  4. 补齐门禁、故障注入、回放测试与评测集。
  5. 发布窗口完成联调验收并上线。

- **Rollback**
  - 触发条件：质量 / 延迟 / 成本门禁持续违约，或关键错误率超阈值。
  - 回滚动作：回退代码与路由到上一稳定版本；研究三表保留，通过事件回放或补偿事件恢复一致性。
  - 保障：上线前完成回滚脚本与演练留痕。

## Best-Practice References

- Deep Agents overview: <https://docs.langchain.com/oss/python/deepagents/overview>
- Customize Deep Agents: <https://docs.langchain.com/oss/python/deepagents/customization>
- Context engineering in Deep Agents: <https://docs.langchain.com/oss/python/deepagents/context-engineering>
- Deep Agents Backends: <https://docs.langchain.com/oss/python/deepagents/backends>
- Deep Agents Subagents: <https://docs.langchain.com/oss/python/deepagents/subagents>
- Deep Agents Skills: <https://docs.langchain.com/oss/python/deepagents/skills>
- Deep Agents Streaming: <https://docs.langchain.com/oss/python/deepagents/streaming>
- Deep Agents Human-in-the-loop: <https://docs.langchain.com/oss/python/deepagents/human-in-the-loop>
- Deep Agents Long-term memory: <https://docs.langchain.com/oss/python/deepagents/long-term-memory>
- Deep Agents repo baseline used in this codebase: `deepagents==0.4.12`（当前实现已按官方文档校准）
- Tavily Credits & Pricing: <https://docs.tavily.com/documentation/api-credits>
- Tavily Search / Extract / Crawl / Research: <https://docs.tavily.com/documentation/api-reference/endpoint/search>
- Jina Reader README (`r.jina.ai`): <https://github.com/jina-ai/reader>
- SearXNG overview: <https://docs.searxng.org/>
- SearXNG Search API: <https://docs.searxng.org/dev/search_api.html>
- Anthropic Multi-Agent Research System: <https://www.anthropic.com/engineering/built-multi-agent-research-system>
- OpenAI Deep Research API Introduction: <https://cookbook.openai.com/examples/deep_research_api/introduction_to_deep_research_api>
- Google Gemini Deep Research announcement (Dec 11, 2024): <https://blog.google/products/gemini/google-gemini-deep-research/>
- LangChain Open Deep Research blog: <https://blog.langchain.com/open-deep-research/>
- Microsoft enterprise deep research: <https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/building-enterprise-grade-deep-research-agents-in-house-architecture-and-impleme/4435256>
- Deep Research survey: <https://arxiv.org/abs/2506.18096>
