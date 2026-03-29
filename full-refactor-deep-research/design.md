## Context

当前代码库中的旧深度研究实现已经删除，仓库需要重新落下一条生产级研究主路径。这份设计直接面向当前事实源：现有公开端点集合、现有前端研究服务文件、现有 FastAPI + Celery + SQLAlchemy + PostgreSQL 部署形态，以及已删除旧研究运行时后的 clean-slate 状态。

本次设计的核心目标不是再发明一套业务层编排，而是把 DeepAgents 作为主 harness 使用，把 planning、subagents、context offloading、skills、memory、HITL、sandbox 等横切能力交给框架；业务层只保留会话、事件、工件、SSE、幂等恢复、审计和门禁等确定性职责。

本设计已按 2026-03-26 的三份研究文档刷新：
- `research-landscape-2026-03-26.md`
- `deepagents-latest-usage-2026-03-26.md`
- `deepagents-implementation-analysis-2026-03-26.md`

## Goals / Non-Goals

**Goals:**
- 直接集成到当前公开端点集合与当前前端研究服务文件。
- 将研究主路径统一为 `session_id` 驱动的 create / plan / stream / interrupt / resume / artifacts 流程。
- 把 `plan-first` 前移为独立 **preflight planner** 阶段，由轻量规划先产出 `research_brief` 与 `plan snapshot`。
- 将正式研究执行统一到 `DeepResearchRuntime`，并最大化利用 DeepAgents harness 能力。
- 将来源路由落实到 `kb | web | paper | hybrid` 与最少数 source-specialized subagents / tools，并在 `web` 路径同时启用 Tavily、Jina Reader、SearXNG，在 `paper` 路径固定启用 arXiv。
- 将 citation 对齐与最终双产物输出收敛到显式 finalizer 阶段。
- 建立 `research_sessions / research_events / research_artifacts` 三表主路径与恢复幂等约束。
- 建立可观测、评测、成本和回滚门禁。

**Non-Goals:**
- 不改动 KB Chat、General Chat、评测链路语义。
- 不在研究模式引入 MCP 工具扩展。
- 不在本次接入除 arXiv 之外的额外学术搜索 provider。
- 不做跨服务拆分。

## Locked Defaults

- 公开研究接口直接接入当前路由集合。
- 当前前端 `frontend/src/services/research.ts` 直接升级为会话化研究服务。
- 研究主标识固定为 `session_id`；设计文档、接口字段、导出链路、前端状态统一围绕 `session_id`。
- `plan-first` 采用服务层 preflight 阶段，不把用户确认建模为主研究阶段内部的隐式状态跳转。
- 正式研究执行默认优先使用 `general-purpose` 子代理做上下文隔离；仅在 `kb/web/paper/citation` 等明显 specialization 场景引入自定义子代理。
- 深度研究 runtime 默认同时装配 Tavily、Jina Reader、SearXNG、arXiv；不使用“全局选择单一搜索 provider”的设计。
- Tavily 在研究模式必须保留 `search`、`extract`、`crawl`、`research` 全能力。
- agent 文件后端仅用于上下文与资产管理；业务事实源始终是数据库三表。
- runtime 显式配置 `checkpointer`；`thread_id` 与 `session_id` 保持稳定映射。
- memory 只保留最小强约束，skills 通过 progressive disclosure 承载细分工作流。

## Canonical Vocabulary

- **session**：研究运行的唯一主标识，对外主键为 `session_id`。
- **preflight planner**：正式研究前的轻量规划阶段，负责产出计划快照与预算信号。
- **research brief**：planner 固化后的研究北极星，包含目标、边界、评价维度、必要约束。
- **plan snapshot**：研究计划快照，至少包含复杂度、子任务、`target_sources`、预算提示、计划状态。
- **target_sources**：子任务级来源路由，固定为 `kb | web | paper | hybrid`。
- **source_provider**：具体检索提供方，网页来源至少区分 `tavily | jina_reader | searxng`，论文来源固定为 `arxiv`。
- **retrieval_method**：本次证据获取方式，例如 `search`、`extract`、`crawl`、`research`、`read`、`fetch`。
- **deep research runtime**：正式研究执行阶段，对应 `create_deep_agent` 单入口运行时。
- **finalizer**：citation/report 收口阶段，负责 canonical citations、结构化输出和最终工件生成。
- **canonical citation**：统一证据结构，无论来源自 KB、网页还是论文，都投影到同一 schema。
- **source_bundle**：runtime 某阶段收拢后的来源包，包含选中证据、去重结果、`coverage_gaps` 与 `interim_summary`。
- **event families**：研究事件统一归入 `research.plan.*`、`research.source.*`、`research.run.*`、`artifact.*`。
- **namespace-aware streaming**：保留 main agent / subagent 命名空间的流式事件协议。
- **子代理模型配置**：仓库内可用 `subagent_model` 作为配置对象字段，但落地到 Deep Agents 时必须映射为 `subagents[*].model`，用于与主代理模型分层控成本。

## Search Provider Matrix

### Tavily
- 角色：深度研究默认网页主 provider，承担高质量搜索、网页抽取、站点爬取与研究型聚合。
- 能力边界：`search`、`extract`、`crawl`、`research` 四条工具链同时启用，不允许在深度研究模式降级为仅 `search`。
- 适用场景：需要结构化搜索结果、站点内扩展抓取、研究型综合摘要时优先。

### Jina Reader
- 角色：提供标准化网页读取与轻搜索入口，补强直接页面消费与难读网页兜底。
- 能力边界：`r.jina.ai` 负责把目标 URL 转换为 LLM-friendly 内容读取结果。
- 适用场景：已知 URL 的快速读取、网页正文标准化、部分站点内容抽取兜底。
- 引用约束：Jina 返回的中转地址不得作为最终 citation 主 URL，最终必须回写原始来源页面。

### SearXNG
- 角色：作为可控 metasearch provider，降低对单商业 provider 的锁定，并提供多引擎聚合搜索。
- 能力边界：通过受控实例的 Search API 调用；需要支持 JSON 格式、类别筛选、时间范围或引擎选择。
- 适用场景：广域网页搜索、低锁定成本 fallback、需要多引擎覆盖面时。
- 运维约束：公共匿名实例不作为生产默认目标；生产应使用受控实例或完成能力验证的固定实例。

### arXiv
- 角色：论文检索唯一首期学术 provider。
- 能力边界：通过 Python `arxiv` 库 direct 调用 arXiv API，支持 search/fetch 与论文结构化元数据获取。
- 适用场景：literature review、benchmark、algorithm survey、paper baseline 构建。

## Decisions

1. **研究流程拆成 preflight planner + deep research runtime + finalizer 三段**
   - 决策：先由轻量 planner 产出计划与预算，再进入正式研究，再进入 citation/report finalization。
   - 原因：降低首阶段成本，避免把审批与高成本执行揉进同一 agent loop。

2. **DeepAgents 是主 harness，不是普通 loop**
   - 决策：`DeepResearchRuntime` 以 `create_deep_agent` 为唯一执行入口，默认保留 TodoList、Filesystem、SubAgent、Summarization、PatchToolCalls 等内建能力。
   - 原因：减少自研 orchestration 与上下文管理负担。

3. **业务层只保留确定性壳层职责**
   - 决策：业务层负责 session、event、artifact、SSE、幂等恢复、审计与门禁；不重写 planning、offloading、subagent、skills、memory 等能力。
   - 原因：把复杂度收敛到 DeepAgents 已擅长的区域。

4. **公开接口直接接入当前端点集合**
   - 决策：研究接口直接落在当前公开 API 命名空间与当前路由组织下。
   - 原因：当前仓库事实是单一路由集合，研究接口应直接收口到这一路径。

5. **当前前端研究服务文件直接升级**
   - 决策：`frontend/src/services/research.ts` 直接重写为 session-based 研究服务。
   - 原因：避免前端契约漂移与多入口维护。

6. **主标识固定为 session_id**
   - 决策：研究域控制、导出、事件流、工件读取全部以 `session_id` 为唯一主标识。
   - 原因：当前设计是 clean-slate 重建，应保持语义收敛。

7. **正式研究默认优先 general-purpose 子代理**
   - 决策：上下文隔离首先依靠 `general-purpose` 子代理；自定义子代理仅用于 source-specific 或 finalization-specific 场景。
   - 原因：DeepAgents 官方已提供继承主技能的默认并行单元，维护成本更低。

8. **只保留最少数 source-specialized subagents / tools**
   - 决策：保留 `kb`、`web`、`paper`、`citation` 四类明显 specialization；避免按任务面无限扩展自定义子代理。
   - 原因：边界清晰且足以让 source-aware routing 真正落地。

9. **source-aware routing 必须是行为差异，不是标签差异**
   - 决策：`paper` 任务优先 direct arXiv；`web` 任务同时启用 Tavily、Jina Reader、SearXNG；`hybrid` 任务先建论文基线，再按需要做网页补证。
   - 原因：只有把来源路由落实到工具和子代理边界，source-aware 才不至于空转。

10. **网页 provider 采用“同时启用 + 策略路由 + 显式 fallback”**
   - 决策：runtime 默认装配 Tavily、Jina Reader、SearXNG 三类网页 provider，不使用单一 provider 开关；由 planner/runtime 根据子任务目标、页面可读性、预算和失败类型选择调用顺序。
   - 原因：深度研究不是普通单轮搜索，需要同时兼顾质量、覆盖面、成本和可恢复性。

11. **Tavily 保留全功能而不是只保留 `search`**
   - 决策：在深度研究模式中显式启用 Tavily `search/extract/crawl/research`，并把其结果统一纳入 canonical evidence。
   - 原因：如果只保留 `search`，就会把大量研究型网页处理逻辑重新搬回业务层。

12. **Jina Reader 只做检索/读取通道，不替代最终引用源**
   - 决策：Jina Reader 可参与 `search/read`，但最终 citation 必须落原始 URL，并在结构化元数据中单独记录 `source_provider=jina_reader`。
   - 原因：Jina 是获取内容的通道，不应污染最终来源归档。

13. **SearXNG 必须走受控实例**
   - 决策：SearXNG 集成按受控实例 Search API 设计，配置中需显式声明实例地址、默认参数与能力探测结果。
   - 原因：公共实例能力漂移较大，不能作为生产事实源。

14. **上下文与文件后端采用明确分层路由**
   - 决策：`CompositeBackend` 路由 `/workspace/`、`/scratch/`、`/plans/` 到 `StateBackend`；`/memories/`、`/skills/` 到 `StoreBackend`。
   - 原因：把 agent 文件系统与业务数据库边界彻底分开。

15. **citation/report finalizer 独立成阶段**
   - 决策：主研究阶段先产出 findings 与 source bundles，finalizer 再完成 citation 对齐、`response_format` 校验和双工件生成。
   - 原因：降低主研究阶段负担，提高评测与诊断清晰度。

16. **response_format 只在最终产物阶段承担强约束**
   - 决策：`response_format` 由 finalizer 使用，`structured_response` 作为 `report_json` 唯一来源。
   - 原因：探索阶段保持弹性，最终阶段保证结构化稳定。

17. **恢复语义保持 session/thread 稳定映射**
   - 决策：`thread_id` 与 `session_id` 保持稳定一一映射，恢复仍使用同一线程上下文。
   - 原因：降低恢复和 tracing 复杂度。

18. **执行能力只允许官方 sandbox backend 暴露**
   - 决策：若研究需要命令执行，只允许通过 `langchain-modal`、`langchain-daytona`、`langchain-runloop` 等官方 sandbox backend 提供 `execute`。
   - 原因：生产研究链路禁止宿主机 shell 风险。

19. **研究门禁必须覆盖论文密集型与混合来源任务**
   - 决策：评测集与门禁必须单独覆盖 `paper` 与 `hybrid` 路径。
   - 原因：否则无法发现 source routing 与 citation 退化。

20. **研究门禁还必须覆盖多网页 provider 路径**
   - 决策：纯网页评测至少覆盖 Tavily 主路径、Jina Reader 参与路径、SearXNG 参与路径三类样本，门禁按 provider 维度拆报。
   - 原因：否则很容易出现只验证 Tavily、其余 provider 形同虚设的问题。

21. **planner 必须产出 research brief，而不只是 task list**
   - 决策：`plan snapshot` 中固定包含 `research_brief`、目标边界、输出要求与预算提示。
   - 原因：外部最佳实践普遍显示 brief 是 runtime 不跑偏的北极星。

22. **SSE 采用 namespace-aware streaming 映射**
   - 决策：研究流不仅映射文本与状态，还要映射 Deep Agents `subgraphs=True` 下的 `namespace`、subagent progress、tool/result updates。
   - 原因：这是前端真正理解研究过程与恢复位置的最小可见性要求。

23. **memory 与 skills 明确分层**
   - 决策：memory 只放始终生效的最小规则；`kb/web/paper/citation` 细分工作流全部通过 skills 按需加载。
   - 原因：避免 prompt 膨胀，并与官方 context engineering 最佳实践对齐。

24. **主 / 子代理模型默认分层**
   - 决策：主代理使用较强模型；子代理通过 `subagents[*].model` 使用更便宜的独立模型；仓库内允许保留 `subagent_model` 作为配置别名，但不得误写为 `create_deep_agent` 顶层参数；finalizer 使用结构化输出稳定的模型。
   - 原因：兼顾复杂任务质量与成本门禁。

25. **runtime 必须显式沉淀 source bundle / interim summary**
   - 决策：在 finalizer 前先保留阶段性 findings、`source_bundle`、`coverage_gaps` 与 `interim_summary`。
   - 原因：便于恢复、回放、评测与最终报告诊断。

## Risks / Trade-offs

- [planner 与 runtime 边界失焦] -> 将 planner 限制为 brief / 计划快照与预算信号，不承担正式资料搜集。
- [业务层重复实现 DeepAgents 能力] -> 明确业务层只保留确定性壳层职责。
- [source routing 只有字段，没有真实执行差异] -> 用 source-specialized tools / subagents 固化边界。
- [多 provider 并启后路由规则混乱] -> 固化 planner/runtime 的 provider policy，并把 `source_provider` / `retrieval_method` 作为事件与工件必填字段。
- [Jina 中转 URL 污染最终引用] -> finalizer 强制写回原始来源 URL，仅将 Jina 记录为 retrieval provider。
- [SearXNG 公共实例能力漂移] -> 仅支持受控实例或已能力验证的固定实例，并在启动时做 capability probe。
- [citation 处理污染主研究阶段] -> 拆出 finalizer。
- [当前前端继续保留旧 run-centric 语义] -> 直接重写当前 `research.ts`，统一为研究会话契约。
- [事件高并发写入导致 sequence 冲突] -> `(session_id, sequence)` 唯一约束 + 冲突重试。
- [memory / skills 不分层导致 prompt 失控] -> 将 memory 压到最小，并把细节流程全部放入 skills。
- [DeepAgents minor 升级引发行为漂移] -> 锁定 minor 版本并执行兼容回归。

## Migration Plan

1. **基础设施阶段（Task 1-3）**：落地三表模型、事件封套、preflight planner 契约与运行时基本骨架。
2. **运行时阶段（Task 4-6）**：落地 DeepResearchRuntime、source-aware tools/subagents、finalizer 与工件链路。
3. **当前端点集成阶段（Task 7-8）**：直接接入当前 API 路由与当前前端研究服务文件。
4. **工作台与观测阶段（Task 9-11）**：完成前端工作台、门禁、回放、故障注入与回滚演练。
5. **文档与收口阶段（Task 12-13）**：同步文档、演示脚本、最终验证与签署。

## Release Gates

- 质量门禁：研究结果评测分数 `>= RESEARCH_GATE_MIN_QUALITY_SCORE`（默认 `0.75`）。
- 性能门禁：关键路径 P95 延迟 `<= RESEARCH_GATE_MAX_P95_MS`（默认 `120000ms`）。
- 成本门禁：单会话成本 `<= RESEARCH_GATE_MAX_SESSION_COST_USD`（默认 `2.0 USD`）。
- 稳定性门禁：中断恢复 E2E、故障注入、事件回放全部通过。
- 可观测工件：`metrics_snapshot` / `gate_snapshot` 必须可按 `session_id` 读取并用于审计。
- 来源覆盖门禁：至少覆盖纯网页、纯论文、网页+论文混合三类任务。
- 契约收口门禁：文档、任务和规格统一使用当前研究单路径术语。

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
