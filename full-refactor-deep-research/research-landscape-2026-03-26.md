# 深度研究（Deep Research）外部方案调研快照（2026-03-26）

## 目标

聚焦以下三类事实源，提炼“生产级深度研究系统”共性架构、设计思想与适用场景：

1. GitHub 高 star 开源项目
2. AI 技术团队 / 技术大牛博客
3. 论文与互联网大厂技术方案

本文只保留对当前仓库重构提案有直接价值的结论，不做泛泛行业综述。

## 调研方法

- GitHub：通过 Agent Reach 的 GitHub 通道执行 `gh search repos ... --sort stars`
- Web / Blog / Paper：通过 Agent Reach 的 Exa / 任意网页通道抓取官方页面、博客、论文摘要
- Deep Agents 官方用法：另见 `deepagents-latest-usage-2026-03-26.md`

## 一、GitHub 高 star 项目

> Star / 更新时间为 2026-03-26 当天查询结果，后续可能变化。

| 项目 | Stars | 主要形态 | 对我们最有价值的信号 |
| --- | ---: | --- | --- |
| `assafelovic/gpt-researcher` | 26017 | planner + execution + publisher | 明确把研究拆成“规划 / 执行 / 汇总”，并强调并行化、citation、可定制领域代理 |
| `dzhng/deep-research` | 18628 | 极简 iterative research loop | 用最少代码证明“clarify + breadth/depth + iterative search + markdown report”这条主路径是成立的 |
| `Alibaba-NLP/DeepResearch` | 18536 | 训练驱动型 deep research 模型 + 完整方案 | 强调 long-horizon information-seeking、IterResearch heavy mode、自动化数据合成与 benchmark 驱动 |
| `langchain-ai/open_deep_research` | 10949 | LangGraph 开放式深度研究代理 | scope / research / write 三段式、supervisor + search workers、MCP 兼容、Deep Research Bench 对齐 |
| `zilliztech/deep-searcher` | 7728 | 私有数据优先的 deep research / agentic RAG | “内网私有数据 + 外网补证”的企业落地路径，强调向量库 / 离线加载 / 企业知识管理 |
| `jina-ai/node-DeepResearch` | 5132 | deep search-first | 重点不是长报告，而是 search-read-reason 循环本身；提醒我们“研究”和“深搜”不是同一层问题 |
| `SkyworkAI/DeepResearchAgent` | 3284 | 分层多代理框架 | 顶层规划 + 下层专才代理 + memory / tracer / optimizer 的系统化设计 |

### 1. `gpt-researcher`

**观察到的设计：**
- planner 负责把研究目标拆成问题；execution/crawler 并行采集；publisher 汇总成最终报告。
- 重点解决 misinformation、速度、determinism、reliability。
- 把“可定制领域研究代理”作为产品能力，而不是只做一个通用 agent。

**启发：**
- 我们保留 `preflight planner + runtime + finalizer` 三段式是对的。
- 研究系统最终必须以“工件”而不是“一段回复”作为主要交付物。

### 2. `dzhng/deep-research`

**观察到的设计：**
- 极简实现，核心是 follow-up clarification、breadth / depth 控制、迭代搜索、并发处理、最后输出 Markdown。
- 依赖 Firecrawl 做网页搜索与内容提取。

**启发：**
- 真实有效的最小主路径不是复杂 DAG，而是：澄清 -> 计划参数化 -> 迭代检索 -> 综合成文。
- 我们的 planner 不宜过重，重点应是复杂度 / 路由 / 预算，而不是先造一个大图。

### 3. `Alibaba-NLP/DeepResearch`

**观察到的设计：**
- 强调 long-horizon 信息搜集能力与 benchmark 驱动。
- 提出 IterResearch / Heavy mode，核心是“周期性 consolidate findings，避免单上下文越跑越脏”。
- 论文与 repo 都强调自动化数据合成、agentic mid-training / post-training。

**启发：**
- 即使我们不训练模型，也应借鉴“阶段性沉淀中间结论、重建工作上下文”的思想。
- `finalizer` 之外，还应有 runtime 内部的压缩 / 中间总结 / source bundle 收口机制。

### 4. `langchain-ai/open_deep_research`

**观察到的设计：**
- 公开强调三阶段：`Scope -> Research -> Write`。
- Scope 中先做 user clarification，再产出 research brief。
- Research 中使用 supervisor agent 组织研究动作；支持多模型、多搜索工具、MCP。
- 与 Deep Research Bench 对齐，评测意识很强。

**启发：**
- 我们现有 `preflight planner` 还应显式承担“brief 固化”职责，不只是吐几个子任务。
- 评测与门禁必须是第一等公民，否则架构会回到 demo agent。

### 5. `deep-searcher`

**观察到的设计：**
- 明确走“私有数据优先，必要时接公网”的企业路线。
- 以离线加载、向量数据库、企业知识库检索为重心。

**启发：**
- 我们把 `kb | web | paper | hybrid` 作为 source routing 是合理的；其中 `hybrid` 本质上就是“私域主证据 + 公域补证”或“论文基线 + 网页上下文”。
- research runtime 不能只面向公网搜索设计，必须从一开始就把 KB 视作一等来源。

### 6. `node-DeepResearch`

**观察到的设计：**
- 强调 search / read / reason 的 iterative process，比长报告更关注“找到答案”的检索效率。
- 明确区分 deep search 与 long-form research report 两类产品目标。

**启发：**
- 我们需要把 runtime 和 finalizer 分离：runtime 面向“找全、找准、找深”，finalizer 面向“写清、写稳、写结构化”。
- 不应把 report generation 反向绑架检索阶段。

## 二、博客 / 技术文章 / 大厂方案

| 来源 | 时间 | 核心观点 | 对我们设计的直接影响 |
| --- | --- | --- | --- |
| Anthropic《How we built our multi-agent research system》 | 2025-06-13 | orchestrator-worker、多子代理并行、search is compression、breadth-first query 特别受益 | 需要保留 lead agent + subagent 的并行研究能力；主代理只接收压缩结果 |
| LangChain《Open Deep Research》 | 2025-07-16 | `Scope -> Research -> Write`、brief 是研究北极星、supervisor agent | planner 要产出 brief / success target，而不只是任务列表 |
| Microsoft《Building Enterprise-Grade Deep Research Agents In-House》 | 2025-07-21 | 企业 deep research 不是 SaaS 复制，而是定制 orchestrator、动态 routing、内外部源融合 | 我们必须把企业壳层（session/event/artifact/audit）与 agent harness 分层 |
| Egnyte《Inside the Architecture of a Deep Research Agent》 | 2025-08-08 | 从 RAG -> ReAct -> 多代理编排；DAG 规划；模型分工；状态图 orchestration | planner / runtime / writer 分层合理；需要显式状态与可审计中间态 |
| Jina《A Practical Guide to Implementing DeepSearch/DeepResearch》 | 2025-02-25 | DeepSearch 崛起与 test-time compute 密切相关；deep search != long report | 研究系统要把“推理 + 搜索循环”和“报告生成”拆开 |
| Onyx《Lessons from building the best Deep Research》 | 2026-02-17 | 不要把 agent 神化；上下文与 prompt 优化比堆层级更关键；大多系统不应超过 2 层代理 | 我们应把自定义子代理数量压到最少，并避免过深层级 |
| Google Gemini Deep Research announcement | 2024-12-11 | 先给研究计划，再让用户看到 / 调整，再长时执行 | 交互式 plan preview 是产品层必要能力 |

### 共性思想

1. **planning-first，但 planner 不能过重**  
   最常见的正确做法是：先做 scope / clarification / brief，再开始长时研究；但真正的资料搜集与写作仍在后续阶段完成。

2. **主代理负责策略，子代理负责压缩后的局部探索**  
   Anthropic 明确把 subagents 视为 context compression 单元，而不是“再造一个总控系统”。

3. **研究系统的核心不是单次回答，而是可审计的研究工件**  
   好的系统会留下 brief、todo、source bundle、timeline、report、trace，而不是只给最后一段话。

4. **企业场景天然要求“内网 / 外网 / 学术”混合来源**  
   这也是我们保留 `kb | web | paper | hybrid` 的根本原因。

5. **真正难点在中间状态治理，而不是首轮搜索**  
   包括：上下文膨胀、路径跑偏、citation 对齐、并发回放、plan 偏移、质量评测。

## 三、论文与技术报告

| 论文 / 报告 | 时间 | 可提炼的架构思想 |
| --- | --- | --- |
| `Deep Research Agents: A Systematic Examination And Roadmap` | 2025-06 / 2025-09(v2) | 给出了 DR agent taxonomy：动态推理、长程规划、多跳检索、迭代工具调用、结构化报告；并强调 API retrieval vs browser exploration、single-agent vs multi-agent 的分类 |
| `WebResearcher: Unleashing unbounded reasoning capability in Long-Horizon Agents` | 2025-09 | 提出 IterResearch：周期性把 findings 合并进 evolving report，同时重建 focused workspace，解决 mono-context 污染与上下文窒息 |
| `Enterprise Deep Research (EDR)` | 2025-11 | 规划代理 + 专项检索代理 + MCP/tool 生态 + visualization + reflection + steering；强调透明、可中途纠偏、todo 可视化 |
| `Tongyi DeepResearch Technical Report` | 2025-11 | 强调 agentic training、长时信息搜集、benchmark 驱动与 open-source 深度研究模型的可能性 |

### 对我们最重要的论文结论

- **研究型 agent 必须同时具备：规划、检索、工具调用、综合成文。** 只有检索或只有写作都不够。
- **多代理不是目的，context isolation / parallel search / steerability 才是目的。**
- **中间态要显式化。** evolving report、todo、source bundle、reflection、steering signal 都应有持久表示。
- **评测必须覆盖开放式长任务。** 传统 QA 指标无法充分代表 deep research 质量。

## 四、跨来源综合：生产级深度研究系统的共性架构

### 1. 最稳定的骨架

```
Clarify / Scope
  -> Brief / Plan Snapshot
  -> Research Runtime (iterative + source-aware + parallel)
  -> Finalizer / Report Writer
  -> Artifacts / Replay / Audit
```

### 2. 共性模块

1. **Scope / Clarification**：先把问题边界、输出期望、评价维度说清楚。
2. **Planner / Brief**：形成稳定北极星，避免 runtime 漫游。
3. **Runtime Supervisor**：决定下一步走哪条搜索 / 阅读 / 子代理路径。
4. **Specialized Workers / Tools**：围绕来源或任务专门化，而不是无限拆角色。
5. **Context Compression**：阶段性总结，避免单上下文越跑越脏。
6. **Finalizer**：把 findings 转成 citation-aligned、结构化、可导出的双产物。
7. **Persistence / Replay / Streaming**：会话、事件、工件、恢复、trace 全部可审计。
8. **Evaluation / Gate**：质量、延迟、成本、覆盖、韧性作为上线门禁，而非附加项。

### 3. 高频反模式

- 只有 search loop，没有稳定 brief / plan，导致跑偏。
- 只有 final answer，没有中间工件，无法恢复和审计。
- 把所有来源都塞给一个代理，导致 source-aware 退化为标签。
- 让主代理直接吞全部原始材料，缺少 subagent 压缩层。
- 为了“高级”无限增加代理角色，实际带来上下文与协调开销。
- 只测 demo case，不做开放式质量门禁与中断恢复验证。

## 五、对本仓库的结论

### 推荐保留

1. `preflight planner + deep research runtime + finalizer` 三段式。
2. `session_id` 驱动的会话、事件、工件单路径。
3. `kb | web | paper | hybrid` 来源路由。
4. 少量 source-specialized subagents，而不是角色泛滥。
5. 双产物：`report_md` + `report_json`。
6. 评测 / 观测 / 回放 / 回滚作为提案内建内容。

### 推荐增强

1. **planner 输出不仅要有子任务，还要有 brief / success target / budget hint。**
2. **runtime 内部要有阶段性压缩机制。** 不仅 finalizer 收口，runtime 也要有 source bundle / interim summary。
3. **SSE 不应只传“文本片段”，还要传 phase、namespace、source bundle、approval / interrupt 状态。**
4. **前端工作台必须把 plan preview、timeline、artifacts、interrupt decision 作为一等视图。**
5. **默认优先 1 个 lead agent + general-purpose subagent + 少量 specialized subagents。** 不建议一开始就走复杂多层 supervisor-of-supervisors。

### 推荐不做

- 不为“研究模式”继续引入 MCP 注入工具。
- 不在首期把 Google Scholar / Semantic Scholar / Crossref 一并接入。
- 不让 runtime 直接承担最终结构化输出约束。
- 不使用宿主机 shell 作为生产研究链路的执行能力。

## 六、参考链接

### GitHub / 项目
- GPT Researcher: <https://github.com/assafelovic/gpt-researcher>
- Open Deep Research（dzhng）: <https://github.com/dzhng/deep-research>
- Tongyi DeepResearch: <https://github.com/Alibaba-NLP/DeepResearch>
- LangChain Open Deep Research: <https://github.com/langchain-ai/open_deep_research>
- DeepSearcher: <https://github.com/zilliztech/deep-searcher>
- DeepResearch（Jina）: <https://github.com/jina-ai/node-DeepResearch>
- DeepResearchAgent（SkyworkAI）: <https://github.com/SkyworkAI/DeepResearchAgent>

### 博客 / 技术文章
- Anthropic: <https://www.anthropic.com/engineering/built-multi-agent-research-system>
- LangChain: <https://blog.langchain.com/open-deep-research/>
- Microsoft: <https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/building-enterprise-grade-deep-research-agents-in-house-architecture-and-impleme/4435256>
- Egnyte: <https://www.egnyte.com/blog/post/inside-the-architecture-of-a-deep-research-agent/>
- Jina: <https://jina.ai/news/a-practical-guide-to-implementing-deepsearch-deepresearch/>
- Google Gemini announcement: <https://blog.google/products/gemini/google-gemini-deep-research/>
- Onyx: <https://onyx.app/blog/building-the-best-deep-research>

### 论文 / 技术报告
- Deep Research Agents: A Systematic Examination And Roadmap: <https://arxiv.org/abs/2506.18096>
- WebResearcher: <https://arxiv.org/html/2509.13309v1>
- Enterprise Deep Research (EDR): <https://arxiv.org/html/2510.17797v2>
- Tongyi DeepResearch Technical Report: <https://arxiv.org/pdf/2510.24701>
