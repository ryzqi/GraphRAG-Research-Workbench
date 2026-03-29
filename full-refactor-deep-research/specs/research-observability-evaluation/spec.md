## ADDED Requirements

### Requirement: 研究链路必须具备端到端可观测关联
系统 MUST 在会话、事件、日志与指标中保留可关联标识（至少含 `session_id`、`trace_id` 与代理名称元数据如 `lc_agent_name`），以支持主代理/子代理跨服务追踪与审计回放。

#### Scenario: 查询单会话执行链路
- **WHEN** 运维或研发针对某个 `session_id` 进行问题排查
- **THEN** 系统 MUST 可关联到该会话的关键事件、日志与指标记录

#### Scenario: 查询子代理执行来源
- **WHEN** 排查某条研究事件由哪个代理（主代理或子代理）产生
- **THEN** 系统 MUST 可通过代理名称元数据定位事件来源并还原调用链路

### Requirement: 可观测数据必须保留 namespace 与模型层级
系统 MUST 在关键 tracing / metrics / logs 中记录 `namespace` 与主/子代理模型层级信息；当子代理采用独立模型配置（映射到 `subagents[*].model`）时，相关事件与成本 MUST 可与主代理模型区分统计。

#### Scenario: 排查子代理成本异常
- **WHEN** 团队分析某次研究任务的成本异常是否来自主代理还是子代理 fan-out
- **THEN** 系统 MUST 能按 `namespace` 与模型层级区分成本与调用量，而不是只提供单一总数

### Requirement: 研究链路必须采集质量、延迟与成本指标
系统 MUST 为研究流程采集并可查询质量、延迟、成本三类核心指标，以支持发布评估与持续优化。

### Requirement: 研究会话必须持久化 metrics 与 gate 工件
系统 MUST 为 research 会话落盘 `metrics_snapshot` 与 `gate_snapshot` 工件，使同一 `session_id` 可同时读取门禁阈值、实测值、回放结果与 fault metrics。

#### Scenario: 审计单会话门禁结果
- **WHEN** 运维读取某个 `session_id` 的研究 artifacts
- **THEN** 响应 MUST 能提供 `metrics_snapshot` 与 `gate_snapshot`，并可回溯到 trace / replay / rollback 事实源

#### Scenario: 发布前读取门禁指标
- **WHEN** 发布流程执行研究链路验收
- **THEN** 系统 MUST 提供可验证的质量分、P95 延迟与单会话成本数据

### Requirement: 研究指标必须区分来源通道
系统 MUST 至少按 `kb`、`web`、`paper`、`hybrid` 四类来源通道拆分关键指标，并进一步按 `source_provider` 维度拆报 Tavily、Jina Reader、SearXNG、arXiv 的成功率、时延、fallback 比例或等价可观测指标。

#### Scenario: 分析论文型研究性能退化
- **WHEN** 团队排查 paper-oriented 研究任务的质量或时延回退
- **THEN** 系统 MUST 能单独查看 `paper` / `hybrid` 来源路径的指标，而不是只提供总体均值

#### Scenario: 分析网页 provider 退化
- **WHEN** 团队排查某次网页研究质量下降是否来自 Tavily、Jina Reader 或 SearXNG
- **THEN** 系统 MUST 能按 `source_provider` 查看对应 provider 的调用量、成功率、时延与 fallback 情况

### Requirement: 发布流程必须执行门禁校验
系统 MUST 在发布前执行研究链路门禁校验，若质量、延迟或成本任一项不满足阈值则阻断发布；门禁阈值 MUST 支持配置化并具备默认值（例如 `RESEARCH_GATE_MIN_QUALITY_SCORE`、`RESEARCH_GATE_MAX_P95_MS`、`RESEARCH_GATE_MAX_SESSION_COST_USD`）。

#### Scenario: 门禁指标未达标
- **WHEN** 发布校验检测到任一核心指标超出阈值
- **THEN** 系统 MUST 阻断发布并输出明确失败原因

### Requirement: 门禁输出必须包含阈值与实测值
系统 MUST 在门禁校验结果中输出每项指标的阈值配置与实测值，支持发布审计与回滚决策追溯。

#### Scenario: 生成发布门禁报告
- **WHEN** 发布流程完成研究链路门禁校验
- **THEN** 报告 MUST 包含质量、延迟、成本各项的阈值、实测值与是否通过标记

### Requirement: 门禁执行记录必须持久化并可追责
系统 MUST 为每次门禁执行持久化结构化记录（至少包含 `release_id`、`gate_run_id`、阈值、实测值、判定结果、执行作业标识与时间戳），并支持关联回滚决议。

#### Scenario: 审计发布门禁决策
- **WHEN** 运维或审计人员查询某次发布门禁结果
- **THEN** 系统 MUST 返回对应门禁执行记录并可关联到回滚记录或放行记录

### Requirement: 研究链路必须具备回放与故障注入验收能力
系统 MUST 支持事件回放验证与故障注入测试，用于验证中断恢复正确性和容错策略有效性。

#### Scenario: 执行故障注入后恢复
- **WHEN** 在研究执行过程中注入依赖故障或超时异常
- **THEN** 系统 MUST 维持约定恢复语义并输出可审计结果

### Requirement: 发布门禁必须覆盖论文密集型与混合来源任务
系统 MUST 在发布前验证纯网页、纯论文、网页+论文混合三类研究任务；若论文密集型或混合来源评测退化，则 MUST 阻断发布。

#### Scenario: 文献综述评测回退
- **WHEN** literature review 或 benchmark comparison 等 paper/hybrid 评测样本低于阈值
- **THEN** 门禁 MUST 标记失败并阻断发布，即使纯网页任务仍然通过

### Requirement: 发布门禁必须覆盖多网页 provider 路径
系统 MUST 在纯网页门禁样本中覆盖 Tavily 主路径、Jina Reader 参与路径、SearXNG 参与路径；若任一 provider 路径持续失败或显著退化，则 MUST 阻断发布。

#### Scenario: SearXNG 路径回退
- **WHEN** SearXNG 路径样本在质量、可用性或延迟上低于阈值
- **THEN** 发布门禁 MUST 标记失败，即使 Tavily 路径与 arXiv 路径仍然通过

### Requirement: 门禁违约必须触发可执行回滚策略
系统 MUST 定义并验证门禁违约触发条件与回滚流程，确保当前研究主路径异常时可回退到稳定版本。

#### Scenario: 生产门禁持续违约
- **WHEN** 上线后在约定窗口内持续触发门禁违约告警
- **THEN** 系统 MUST 按预案触发回滚并记录回滚执行结果

### Requirement: rollback drill 必须产出留痕记录
系统 MUST 提供可执行的 rollback drill 脚本与 runbook，并在 dry-run 或真实演练后生成结构化留痕记录。

#### Scenario: 执行 rollback drill
- **WHEN** 团队运行 rollback drill 脚本
- **THEN** 系统 MUST 生成可审计记录，至少包含当前提交、门禁阈值、目标回滚提交与 planned rollback steps
