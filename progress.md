# Progress

## 2026-04-21

### Session Start

- 创建持久化跟踪文件，准备执行 Deep Research 真实链路回归。
- 已确认核心 API 入口、研究启动入口、工件接口和导出服务的关键代码位置。
- 已确认研究链路需要 `dispatch` worker 和 `research,export` worker 同时在线。
- 已确认本地 Postgres / Redis / MinIO / SearXNG 容器处于运行状态。
- 下一步：创建日志目录，启动 backend 与必要 worker，并执行健康探测。

### 启动脚本修正

- 新增 `scripts/deep_research/start_backend_workers.ps1`、`stop_backend_workers.ps1`、`run_real_flow.ps1`，用于真实回归、日志落盘和进程重启。
- 首次执行停止脚本时发现当前环境下 `Get-CimInstance Win32_Process` 被拒绝访问，已改为基于 `backend/logs/deep_research_process_state.json` 管理 PID。
- 随后又发现停止脚本存在 PowerShell 插值语法错误 `PID=$pid:`，已修正为 `PID=${pid}`。
- 前台手动启动 backend 时确认 `uv run` 被全局缓存目录权限阻塞：`D:\uv\uv_cache` 拒绝访问。
- 已把 Deep Research 启动脚本与 runner 脚本统一改为使用仓库本地 `.uv-cache`，并把后台启动方式改为 `Start-Process -File ... -RedirectStandardOutput/-RedirectStandardError`，方便稳定落日志。
- 为避开当前工具环境中后台进程托管不稳定，新增 `scripts/deep_research/orchestrate_real_flow.ps1`，改成在单次 shell 会话中拉起 backend + dispatch/noncore worker、跑完整真实链路、再统一收尾。
- 第一轮整编排已验证 `/health`、`/ready`、`/model-config` 成功，但 `run_real_flow.ps1` 在写 flow 日志文件时因文件占用失败。
- 已将 `Add-StepLog()` 改为基于 `System.IO.File.WriteAllText` 的带重试原子写法，准备重跑真实链路。

### Runtime 修复与真实回归

- 新增 `backend/tests/test_web_search_client.py`，先红后绿复现并锁定 `WebSearchClient` 与 `_LoopLocalHttpClientProxy` 的 timeout 契约缺陷。
- 已在 `backend/src/app/agents/tools/web_search_client.py` 增加 timeout fallback，在 `backend/src/app/worker/deep_research_runtime_cache.py` 为 loop-local proxy 补 timeout 属性，并抽出 `build_http_timeout()` 供复用。
- 定向验证已通过：
  - `uv run pytest tests\\test_web_search_client.py tests\\test_http_client.py -q -p no:cacheprovider`
  - `uv run ruff check src\\app\\agents\\tools\\web_search_client.py src\\app\\integrations\\http_client.py src\\app\\worker\\deep_research_runtime_cache.py tests\\test_http_client.py tests\\test_web_search_client.py`
- 随后发现第二个真实阻塞来自联网环境：backend 共享 `httpx` client 固定 `trust_env=False`，导致 Deep Research runtime 无法使用当前主机代理访问 `Tavily` 与 `Jina`。
- 已按用户确认移除 `backend/src/app/integrations/http_client.py` 中的 `trust_env=False`，并将 `backend/tests/test_http_client.py` 调整为验证 `client._trust_env is True`。
- 移除 `trust_env=False` 后再次通过定向验证，并执行 backend graphify rebuild。

### 最终真实通过证据

- 真实全链路编排命令：
  - `& '.\\scripts\\deep_research\\orchestrate_real_flow.ps1'`
- 最终成功结果：
  - `completed_at`: `2026-04-21T19:51:59.1599128+08:00`
  - `session_id`: `67e8eb9b-413d-46fd-ba64-44ce95161d3f`
  - `final_status`: `final`
  - `export_id`: `0d9776f1-a7da-4142-9c06-092b63e14426`
- 关键产物已生成：
  - `report_md`
  - `report_json`
  - `source_ledger_json`
  - `coverage_matrix_json`
  - `presentation_snapshot`
- 导出已成功下载到本地证据文件：
  - `backend/logs/deep_research_export_20260421_194345.pdf`
- 全流程证据日志：
  - `backend/logs/deep_research_e2e_flow_20260421_194345.json`
  - `backend/logs/backend_orch_20260421_194335.err.log`
  - `backend/logs/worker_dispatch_orch_20260421_194335.err.log`
  - `backend/logs/worker_noncore_orch_20260421_194335.err.log`
