## ADDED Requirements

### Requirement: 深度研究运行时必须单入口执行
系统 MUST 通过 `create_deep_agent` 作为深度研究的唯一执行入口，并在运行时按最新官方用法显式装配 `memory=[AGENTS.md...]`、`skills=[dir...]`、`interrupt_on`、`checkpointer` 与 `store`，禁止出现并行的旧引擎执行路径。

#### Scenario: 创建研究会话时构建统一运行时
- **WHEN** 服务层收到新的研究会话执行请求
- **THEN** 系统 MUST 使用统一的 DeepAgents 运行时构建流程并返回可执行会话上下文

### Requirement: 研究运行时必须生成 source-aware 研究计划
系统 MUST 在进入高成本外部研究前生成 source-aware 计划，至少区分 `kb`、`web`、`paper`、`hybrid` 四类目标来源，并向 orchestrator 提供 `research_brief`、复杂度、预算提示或等价执行信号。

#### Scenario: 启动论文综述类研究任务
- **WHEN** 用户提交 literature review、benchmark 对比或算法综述类研究问题
- **THEN** 系统 MUST 先生成包含 `paper` 或 `hybrid` 目标来源的研究计划，再启动后续检索与综合步骤

### Requirement: 深度研究运行时必须同时启用四类外部检索能力
系统 MUST 在深度研究模式同时启用 Tavily、Jina Reader、SearXNG、arXiv 四类外部检索能力；不得通过单一全局开关把运行时裁剪为单 provider 模式。

#### Scenario: 初始化深度研究工具集
- **WHEN** 系统为研究会话构建工具注册表
- **THEN** 返回的研究工具集 MUST 同时包含 Tavily、Jina Reader、SearXNG、arXiv 对应工具，并允许 runtime 按子任务策略选择调用

### Requirement: Tavily 在深度研究模式必须保留全功能
系统 MUST 在深度研究模式启用 Tavily `search`、`extract`、`crawl`、`research` 四条能力链路，而不是仅保留 `search`。

#### Scenario: 网页研究需要从搜索扩展到抽取与爬取
- **WHEN** 某个网页研究子任务需要从搜索结果继续读取正文、扩展站内页面或生成 research-style 汇总
- **THEN** runtime MUST 可直接调用 Tavily `extract`、`crawl`、`research`，而不是回退到自制胶水逻辑

### Requirement: Jina Reader 必须提供读取能力
系统 MUST 集成 Jina Reader 的 `r.jina.ai` 读取能力，用于已知 URL 内容标准化和难读页面兜底。

#### Scenario: 对已知网页 URL 做标准化读取
- **WHEN** runtime 已确定目标网页 URL 且需要获取 LLM-friendly 正文
- **THEN** 系统 MUST 可通过 `r.jina.ai` 路径读取页面内容，并将结果与原始 URL 绑定

### Requirement: SearXNG 必须通过受控 Search API 集成
系统 MUST 通过受控 SearXNG 实例的 Search API 集成网页搜索能力，并支持 JSON 响应、类别/时间范围/引擎筛选或等价能力；不得把匿名公共实例当作生产默认事实源。

#### Scenario: 使用 SearXNG 做广域网页搜索
- **WHEN** runtime 为某个网页研究子任务选择 SearXNG
- **THEN** 系统 MUST 调用受控实例 Search API 并返回可解析 JSON 结果，而不是依赖不可验证的 HTML 抓取

### Requirement: 研究运行时必须使用当前 LangGraph graph stream contract
系统 MUST 对研究运行时内部的 `invoke` / `ainvoke` / `stream` / `astream` 统一采用 `version="v2"`，并以 `GraphOutput.value`、`GraphOutput.interrupts` 以及 `StreamPart {type, ns, data}` 作为流式与中断桥接的标准结构，禁止继续依赖旧版 `__interrupt__` 或 tuple 风格流输出。

#### Scenario: 运行时处理流式事件与中断
- **WHEN** 研究运行时执行流式输出或命中中断
- **THEN** 系统 MUST 从 `version="v2"` 返回值中读取统一的状态、interrupts 与流分片结构，并据此生成外部 SSE 事件

### Requirement: 研究运行时必须对齐 deepagents 最新中间件栈
系统 MUST 对齐当前 deepagents 官方默认能力：至少启用 `TodoListMiddleware`、`FilesystemMiddleware`、`SubAgentMiddleware`，并保留 `SummarizationMiddleware` 与 `PatchToolCallsMiddleware`；当模型供应商为 Anthropic 时 MUST 启用 `AnthropicPromptCachingMiddleware`；当配置 `memory`、`skills`、`interrupt_on` 时 MUST 分别启用对应中间件。

#### Scenario: 运行时初始化中间件管线
- **WHEN** 系统初始化研究运行时
- **THEN** 运行时 MUST 按当前配置得到可审计的中间件装配结果，并支持计划、文件系统、子代理、摘要与工具调用修复行为

### Requirement: 文件系统中间件必须启用大结果落盘策略
系统 MUST 为 `FilesystemMiddleware` 启用大工具上下文落盘能力；未显式覆盖时 `tool_token_limit_before_evict` MUST 采用官方默认阈值（`20000` token），并同时覆盖超长工具输入、超长工具结果以及 `write_file` / `edit_file` 回显，避免直接挤占对话上下文。

#### Scenario: 工具返回超长内容
- **WHEN** 检索或抓取工具返回超过阈值的大文本结果
- **THEN** 系统 MUST 将完整结果写入受控文件系统并在消息中返回可追踪引用，而非将完整内容直接保留在会话上下文

#### Scenario: 工具输入或文件回显过长
- **WHEN** 工具调用参数、文件写入回显或编辑回显超过落盘阈值
- **THEN** 系统 MUST 以文件引用替换冗长上下文，并保留可复查的文件路径或预览信息

### Requirement: 论文检索必须通过 direct arXiv 工具执行
系统 MUST 在论文、benchmark、algorithm、technical survey、literature review 等 paper-oriented 子任务中，通过 Python `arxiv` 库 direct 调用 arXiv API 获取论文元数据；不得仅依赖 Tavily 对 `arxiv.org` 的域名过滤来替代论文检索。

#### Scenario: 执行论文密集型研究子任务
- **WHEN** orchestrator 将某个子任务标记为 `paper` 来源
- **THEN** 系统 MUST 使用 direct arXiv 工具返回至少论文标题、作者、摘要或摘要摘录、发布日期以及 `abs`/`pdf` 链接

### Requirement: 网页来源路由必须支持 provider 策略与 fallback
系统 MUST 为 `web` 子任务定义显式 provider 策略，能够在 Tavily、Jina Reader、SearXNG 之间执行首选、补充或 fallback 调用，并记录每次 evidence 的 `source_provider` 与 `retrieval_method`。

#### Scenario: 主 provider 失败后继续网页研究
- **WHEN** `web` 子任务的首选 provider 因超时、限流或结果不足失败
- **THEN** runtime MUST 能在同一子任务上下文中切换到其他已启用 provider，并将切换记录写入事件与中间工件

### Requirement: 研究运行时必须按复杂度伸缩 effort
系统 MUST 根据查询复杂度和研究类型显式调节子代理 fan-out 与工具预算，避免 simple 查询过度委派，或 complex research 委派不足。

#### Scenario: 简单事实查询进入研究运行时
- **WHEN** 查询被分类为 simple factual lookup
- **THEN** 系统 MUST 限制子代理数量和工具调用预算，不得无约束并发扩散

### Requirement: 研究运行时必须支持主子代理模型分层
系统 MUST 显式区分主代理模型与子代理模型配置；当研究任务启用子代理时，系统 MUST 能按配置为子代理使用独立模型层级，并通过 `subagents[*].model`（或等价映射）落地到 Deep Agents 运行时，同时将其纳入预算与门禁。

#### Scenario: 复杂研究任务需要并行子代理
- **WHEN** runtime 为复杂任务派生多个 subagents
- **THEN** 系统 MUST 能为这些 subagents 应用显式的独立模型配置，并把该配置写入 `subagents[*].model`，而不是默认与主代理模型完全同配

### Requirement: 运行时必须支持分层后端策略
系统 MUST 支持 `StateBackend`、`StoreBackend` 或 `CompositeBackend` 的分层策略：会话内临时工作文件可使用 `StateBackend`，跨线程长期记忆与技能资产 MUST 落在可持久后端（`StoreBackend` 或受控 `FilesystemBackend`）并在执行前完成预置；其中 `memory` 源 MUST 是 `AGENTS.md` 文件路径，`skills` 源 MUST 是技能目录路径。

#### Scenario: 会话需要读取 memory/skills 文件
- **WHEN** 研究会话启用 `memory` 或 `skills` 配置
- **THEN** 系统 MUST 在代理执行前保证对应文件在目标 backend 中可读，并记录后端类型与命名空间来源

### Requirement: 研究运行时必须禁用 MCP 工具装配
系统 MUST 在研究模式工具注册中排除 MCP 工具入口，研究任务仅可调用内置检索与处理工具链。

#### Scenario: 运行时装配工具集
- **WHEN** 运行时初始化研究工具集合
- **THEN** 返回的工具列表 MUST 不包含任何由 `load_mcp_tools` 或等价 MCP 装配函数注入的工具

### Requirement: 研究运行时必须执行安全基线约束
系统 MUST 在研究工具执行链路启用最小权限安全基线，至少包括工具调用域名白名单与执行沙箱权限限制；若启用 `execute` 类命令执行工具，MUST 仅在受控沙箱 backend 内运行。

#### Scenario: 访问非白名单外部域名
- **WHEN** 研究工具尝试访问未在白名单内的外部域名
- **THEN** 系统 MUST 拒绝该调用并记录可审计安全事件

### Requirement: 命令执行能力必须基于官方 sandbox backend
系统 MUST 仅在确有需要时启用 DeepAgents 内置 `execute`，并通过官方 sandbox backends（如 `langchain-modal`、`langchain-daytona`、`langchain-runloop`）提供隔离执行环境；生产研究链路 MUST NOT 依赖宿主机 shell 或 `LocalShellBackend`。

#### Scenario: 研究流程需要执行命令
- **WHEN** 研究任务规划中出现代码执行、安装依赖或 shell 命令步骤
- **THEN** 系统 MUST 将该能力绑定到受控 sandbox backend，而不是直接暴露宿主机执行权限

### Requirement: 研究证据必须 canonicalize
系统 MUST 将 KB、网页与论文来源统一归一化为 canonical evidence / citation schema，至少保留 `source_type`、`source_provider`、`retrieval_method`、`source_id`、`title`、`url`、`origin_url`、`accessed_at`；论文来源额外保留 `arxiv_id`、`authors`、`published_at`、`pdf_url`（若可用）。

#### Scenario: 研究流程同时使用网页与论文证据
- **WHEN** 同一会话混合使用 Tavily 与 arXiv 结果
- **THEN** 系统 MUST 输出可统一消费的 canonical citations，并能区分 `web` 与 `paper` 来源类型

#### Scenario: Jina Reader 或 SearXNG 参与网页证据获取
- **WHEN** 某条网页证据经由 Jina Reader 或 SearXNG 获取
- **THEN** canonical citation MUST 保留 `source_provider`，并把最终 `origin_url` 指向原始网页而非中转地址

### Requirement: runtime 必须显式沉淀中间研究收口物
系统 MUST 在 finalizer 前显式生成并更新 `source_bundle`、`interim_summary` 与 `coverage_gaps`，使恢复、回放、评测与最终报告诊断都能读取到阶段性研究状态。

#### Scenario: runtime 完成一轮来源收敛
- **WHEN** 主代理或子代理完成某一轮资料检索与综合
- **THEN** 系统 MUST 先落地对应 `source_bundle`、`interim_summary` 与 `coverage_gaps`，再进入下一轮扩展研究或最终 finalizer

### Requirement: 运行时必须支持中断与恢复的同线程延续
系统 MUST 在启用 `interrupt_on` 时强制配置 `checkpointer`，并在中断后基于同一 `session_id` 与 `thread_id` 恢复执行；恢复后的步骤可继续产生有序事件与最终工件。

#### Scenario: 中断后恢复研究执行
- **WHEN** 会话进入 interrupted 状态后收到 resume 决策
- **THEN** 系统 MUST 在同一 `session_id` 与 `thread_id` 上恢复执行并继续输出后续研究事件

### Requirement: 运行时必须约束子代理并发与预算
系统 MUST 为研究会话施加子代理并发与预算约束（至少包括并发上限、工具调用上限、时间预算、token 预算），并在超限时执行可审计的降级或终止策略。

#### Scenario: 子代理并发达到上限
- **WHEN** 研究流程尝试启动超过并发上限的子代理任务
- **THEN** 系统 MUST 阻止超限启动并记录预算约束事件

### Requirement: 子代理执行必须默认上下文隔离
系统 MUST 默认采用上下文隔离策略，子代理仅接收任务摘要与必要工件引用，不得无约束共享完整上游历史。

#### Scenario: 子代理接收执行上下文
- **WHEN** 调度器为子代理分配新任务
- **THEN** 传入上下文 MUST 不包含完整上游会话历史，仅包含任务所需最小上下文

### Requirement: 子代理技能与中断策略必须显式可控
系统 MUST 明确区分通用子代理与自定义子代理的能力继承：`general-purpose` 子代理可继承主代理 `skills`，自定义子代理默认不继承主代理 `skills` 且必须显式配置；子代理 `interrupt_on` 配置 MUST 可覆盖主代理同名工具配置。

#### Scenario: 自定义子代理执行技能任务
- **WHEN** 自定义子代理被调度执行需要技能支持的任务
- **THEN** 若未显式配置该子代理 `skills`，系统 MUST 不假定其继承主代理技能，并返回可诊断的能力缺失信号或降级路径

### Requirement: 运行时必须支持结构化输出产物
系统 MUST 使用 `response_format` 生成并校验结构化输出，将校验后的 `structured_response` 持久化为 `report_json` 工件，同时保留可读文本工件 `report_md`。

#### Scenario: 进入 finalizer 产物收口阶段
- **WHEN** 研究流程完成 findings 汇总并开始生成最终报告
- **THEN** 系统 MUST 由 finalizer 生成结构化与可读双工件，并将其写入工件存储
