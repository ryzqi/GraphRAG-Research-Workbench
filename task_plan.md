# Deep Research 真实链路回归任务计划

## 目标

- 在当前环境完成一次真实 Deep Research 端到端回归：
  提问 -> 澄清 -> 启动研究 -> 等待最终报告生成 -> 导出报告。
- 全程记录日志、关键响应、失败症状、修复动作与重跑结果。
- 若失败，按真实故障做最小修复，重启后端后继续重跑，直到跑通或确认外部阻塞。

## 边界

- 仅处理与本次 Deep Research 真实链路失败直接相关的问题。
- 不顺手重构无关模块，不扩展到普通 chat、前端或无关 worker。
- 只有在真实链路或直接对应验证失败时才改代码。

## 验收标准

- 成功创建 research session。
- 能完成必要 clarification 轮次并进入 `plan_ready` 或直接具备可启动条件。
- 能成功启动研究任务并推进到最终报告生成完成。
- 能通过导出接口或导出任务拿到有效报告产物。
- 全过程有可追踪日志与关键证据文件。

## 阶段

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 1. 建立记录与读取规则 | completed | 已创建计划、发现、进度文件并确认入口 |
| 2. 环境探测与启动 | completed | 已确认 backend、worker、数据库、Redis、模型与本机代理可用性 |
| 3. 真实链路执行与日志采集 | completed | 已完成从提问到报告导出的真实链路并落盘证据 |
| 4. 故障定位与最小修复 | completed | 已完成 runtime timeout 契约修复与 http client 代理修复 |
| 5. 重启与回归复跑 | completed | 已重启后端并完成最终通过回归 |

## 日志与证据路径

- 后端运行日志：`backend/logs/backend_deep_research_e2e_*.log`
- Worker 运行日志：`backend/logs/worker_dispatch_deep_research_e2e_*.log`、`backend/logs/worker_noncore_deep_research_e2e_*.log`
- 真实链路请求/响应日志：`backend/logs/deep_research_e2e_flow_*.json`
- 导出文件落点：优先通过 `/api/v1/exports/{id}/download` 拉取到本地证据目录

## 错误记录

| 时间 | 阶段 | 症状 | 根因 | 处理 |
| --- | --- | --- | --- | --- |
| 2026-04-21 18:48 | runtime | `worker_noncore` 中 `WebSearchClient._http_request_timeout()` 抛 `AttributeError: '_LoopLocalHttpClientProxy' object has no attribute 'timeout'` | Deep Research worker 注入的是 loop-local shared http client proxy，但 `web_search_client` 直接假定注入对象具有 `.timeout` 属性 | 补 `test_web_search_client.py` 先红后绿；为 `web_search_client` 增加 timeout fallback，为 loop-local proxy 补 timeout 属性，并通过定向 pytest/ruff |
| 2026-04-21 19:14 | runtime | 研究长时间停在 `running`，live board 明确显示 `Breadth-pass failed repeatedly due to upstream tool errors in web search` | backend 共享 `httpx` client 强制 `trust_env=False`，导致运行时绕过当前主机已配置的 `127.0.0.1:7890` 代理；Tavily/Jina 外网请求均 `ConnectError` | 删除 `create_http_client()` 中的 `trust_env=False`，补齐定向测试，重建 graphify，重启后端和 worker 后重跑真实链路成功 |
