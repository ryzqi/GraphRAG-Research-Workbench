# Findings

## 当前任务

- Deep Research 真实链路回归与修复。

## 已确认事实

- `POST /api/v1/research/sessions` 创建会话。
- `POST /api/v1/research/sessions/{session_id}/clarification` 提交澄清回答。
- `POST /api/v1/research/sessions/{session_id}/start` 启动研究，并触发 research outbox dispatch。
- `GET /api/v1/research/sessions/{session_id}/artifacts` 可读取研究工件。
- `ExportService.create_export()` 会创建导出任务，并通过 Celery 发送 `app.worker.tasks.export.run_export`。
- `ResearchExporter.export()` 依赖 `report_md` 与 `report_json` 工件，两者缺失会返回 `ARTIFACT_INCOMPLETE`。

## 本次会话发现

- 仓库根 README 已给出 Windows/PowerShell 启动命令：
  `uv run uvicorn app.main:app ...`、`uv run celery -A app.worker.celery_app worker ...`。
- `start` 研究会话后会调用 `trigger_outbox_dispatch()`，该调用把 `dispatch_research_outbox` 投递到 `dispatch` 队列，因此真实回归至少需要 `dispatch` worker 与 `research,export` worker。
- 当前 `.env` 指向本机依赖：
  PostgreSQL `localhost:5433`、Redis `localhost:6379`、MinIO `localhost:9000`、SearXNG `127.0.0.1:18080`。
- 依赖容器当前已运行：`mkb_postgres`、`mkb_redis`、`mkb_minio`、`mkb_searxng`、`mkb_milvus` 等。
- 仓库内未找到现成的 Deep Research 全链路真实回归脚本，本次需要自建最小 PowerShell/API 回归脚本。
- 首次前台启动 backend 时，`uv run` 在真正执行应用前就失败，报错：
  `failed to open file D:\uv\uv_cache\sdists-v9\.git: 拒绝访问。`
  这说明当前会话默认 `uv` 全局缓存路径不可用，必须显式切到仓库内可写缓存目录。
- 单次编排脚本已确认 backend `/health`、`/ready`、`/model-config` 都可正常返回，说明后端与依赖可用。
- 本轮真实链路未进入 `create_session`，阻塞在 `run_real_flow.ps1` 的 `Add-StepLog()`：写 `deep_research_e2e_flow_*.json` 时遭遇文件占用。
- 该问题属于回归脚本日志落盘实现，不是 Deep Research 业务接口错误。
- Deep Research runtime cache 给 `WebSearchClient` 注入的是 `_LoopLocalHttpClientProxy`；旧实现直接读取 `client.timeout`，会在 runtime 阶段触发 `AttributeError` 并阻塞 breadth-pass。
- 修复 `WebSearchClient` timeout 契约后，真实链路继续前进，但 live board 仍显示 `Breadth-pass failed repeatedly due to upstream tool errors in web search. Research is blocked. Waiting for user guidance.`。
- 对当前环境做 fresh 核验后确认：
  - `https://api.tavily.com` 与 `https://r.jina.ai` 在 backend 进程默认 httpx 配置下均为 `ConnectError`。
  - 当前 PowerShell 进程已存在 `HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy` = `http://127.0.0.1:7890`。
  - WinHTTP 当前代理也指向 `127.0.0.1:7890`。
  - `httpx.AsyncClient(proxy='http://127.0.0.1:7890', trust_env=False)` 可成功访问 `api.tavily.com` 与 `r.jina.ai`。
- 由此确认第二个真实根因不是研究逻辑本身，而是 backend 共享 `httpx` client 在 `create_http_client()` 中固定 `trust_env=False`，导致 Deep Research runtime 绕过本机代理，外网 provider 全部失联。
- 本地 `SearXNG` 服务本身可达，但当前 engines/查询组合在该研究题目上返回 `0` 条结果，因此不能单独承担该次研究所需的 breadth-pass 证据收集。
- 删除 `trust_env=False` 后，Deep Research 真实链路已成功完成：
  - session `67e8eb9b-413d-46fd-ba64-44ce95161d3f`
  - export `0d9776f1-a7da-4142-9c06-092b63e14426`
  - 最终状态 `final`
  - PDF 导出文件已成功下载
