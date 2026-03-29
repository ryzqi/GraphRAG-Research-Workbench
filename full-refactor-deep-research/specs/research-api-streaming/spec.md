## ADDED Requirements

### Requirement: 当前研究会话创建接口必须异步受理
系统 MUST 在当前公开端点集合中提供研究会话创建接口，并在受理后返回可追踪的 `session_id` 与初始状态，而不是同步阻塞直到研究完成。

#### Scenario: 创建研究会话
- **WHEN** 客户端调用当前研究创建接口提交合法请求
- **THEN** 系统 MUST 返回受理成功状态并包含 `session_id`

### Requirement: 当前研究接口必须支持 preflight planner
系统 MUST 支持“先产出计划、再决定是否执行”流程；当请求启用 `plan-first` 或被判定为高成本外部研究时，必须先返回或推送 `plan snapshot`，再进入正式研究；该 `plan snapshot` 至少包含 `research_brief`、复杂度、子任务、`target_sources` 与预算提示。

#### Scenario: 请求计划预览
- **WHEN** 客户端以需确认模式创建研究会话
- **THEN** 系统 MUST 返回 `session_id` 与可确认的计划摘要，而不是直接进入外部研究

### Requirement: SSE 流必须输出标准事件封套
系统 MUST 通过当前研究流接口按顺序推送标准事件封套，事件至少包含 `event_id`、`sequence`、`timestamp`、`event_type`、`session_id`、`payload`、`trace_id`、`phase`、`namespace` 与 `lc_agent_name`。

#### Scenario: 订阅会话事件流
- **WHEN** 客户端连接指定 `session_id` 的研究流
- **THEN** 系统 MUST 按 `sequence` 递增顺序发送事件

### Requirement: 来源相关事件必须暴露 provider 元数据
系统 MUST 在 `research.source.*` 事件及相关 payload 中暴露 `source_provider` 与 `retrieval_method`；当网页证据来自 Jina Reader 等中转通道时，还 MUST 暴露 `origin_url` 或等价原始来源字段。

#### Scenario: 前端展示网页 provider 路由
- **WHEN** runtime 发出某条网页来源事件
- **THEN** 当前研究流 MUST 让前端可区分该事件来自 Tavily、Jina Reader 还是 SearXNG，并可读取其原始来源 URL

### Requirement: SSE 流必须保留 namespace-aware subgraph 语义
系统 MUST 将 Deep Agents `subgraphs=True` 下的 main agent / subagent 命名空间保留到外部 SSE 协议中；当事件来自子代理时，MUST 提供稳定的 `namespace`，并在可用时提供 `subagent_name` 或等价映射字段。

#### Scenario: 子代理产生研究进度事件
- **WHEN** 某个 subagent 在 research runtime 中产出进度、工具或结果事件
- **THEN** 当前研究流 MUST 向前端暴露对应 `namespace`，而不是将其扁平化为无法区分来源的通用状态事件

### Requirement: 计划与来源事件必须采用 canonical event family
系统 MUST 将计划阶段事件归入 `research.plan.*`，将来源路由事件归入 `research.source.*`，并保持命名稳定可枚举。

#### Scenario: 前端消费计划与来源事件
- **WHEN** 工作台依赖事件类型驱动计划预览与来源标签渲染
- **THEN** 服务端 MUST 提供稳定的 `research.plan.*` 与 `research.source.*` 事件族

### Requirement: 当前流接口必须支持断线续传
系统 MUST 支持 `Last-Event-ID` 续流；当 `Last-Event-ID` 与 `resume_from_event_id` 同时存在时，服务端 MUST 以 `Last-Event-ID` 为优先续流游标。

#### Scenario: 客户端断线重连
- **WHEN** 客户端携带 `Last-Event-ID` 重新连接同一 `session_id`
- **THEN** 系统 MUST 从该游标之后的首条事件继续推送

### Requirement: 当前研究接口必须支持中断与恢复协议
系统 MUST 提供 interrupt / resume 接口，并保证状态迁移遵循 `running -> interrupted -> resumed -> running/final` 约束。

#### Scenario: 提交恢复决策
- **WHEN** interrupted 会话收到 resume 决策
- **THEN** 系统 MUST 继续执行并在事件流中体现状态变化

### Requirement: 恢复请求必须具备幂等语义
系统 MUST 支持 `idempotency_key`，避免重复恢复请求导致重复状态推进或重复副作用。

#### Scenario: 重复提交同一恢复请求
- **WHEN** 客户端对同一会话重复提交语义等价的 resume 请求
- **THEN** 系统 MUST 返回一致结果且不重复推进状态

### Requirement: 当前 artifacts 接口必须暴露门禁工件
系统 MUST 通过当前 artifacts 接口暴露 `metrics_snapshot` 与 `gate_snapshot`，供工作台、导出诊断与发布审计读取。

#### Scenario: 读取 observability 工件
- **WHEN** 客户端调用 `GET /api/v1/research/sessions/{session_id}/artifacts`
- **THEN** 响应 MUST 可包含 `metrics_snapshot` 与 `gate_snapshot`，且其内容与当前 `session_id` 会话一致
