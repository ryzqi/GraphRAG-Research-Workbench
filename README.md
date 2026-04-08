# 多知识库 + 多智能体协作知识代理系统

本仓库为毕业设计代码与演示脚手架，目标是实现：多知识库隔离与联合检索、可追溯证据清单、多智能体协作、深度研究与导出复现。

## 仓库结构

- `frontend/`：Next.js 前端。
- `backend/`：FastAPI、Celery、数据接入与研究运行时。
- `infra/`：Podman 基础设施、SearXNG 配置与本地数据目录。
- `scripts/`：启动、验收、数据重置脚本。
- `docs/`：当前架构与 Research API 契约文档。

## 功能入口

- 根路径 `/`：普通代理。
- 顶部导航：普通代理 → 知识库问答 → 知识库管理 → 深度研究 → MCP 扩展。

## Deep Research 当前事实源

- 统一业务主标识：`session_id`
- 统一公开前缀：`/api/v1/research/sessions*`
- 统一工件读取：`research_artifacts`
- 最终报告：`report_md` / `report_json`
- 可观测工件：`metrics_snapshot` / `gate_snapshot`
- 详细契约：`docs/api_contract_research.md`

## 模型配置

- 运行时模型主配置（供应商、Base URL、API Key、模型列表、全局生效模型）通过前端「模型配置」页面维护。
- `.env` 仍用于超时、Embedding、搜索等服务配置，但 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 不再是运行时主配置来源。

## 环境要求

- Windows 11
- Python 3.13+
- Node.js `^20.19.0 || >=22.12.0`
- `uv`
- Podman（建议 Podman Desktop；`podman-compose` 仅作为回退方式）

## 快速开始

1. 复制 `.env.example` 为 `.env`，按需填写密钥与端口。
2. 在仓库根目录执行一键启动：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

常用参数：

- `-SkipInfra`：跳过 Podman 基础依赖
- `-NoDetachInfra`：基础依赖前台运行
- `-SkipBackend`
- `-SkipWorker`
- `-SkipFrontend`
- `-RunMigrate`：显式执行数据库迁移
- `-Verbose`

补充说明：

- 默认跳过数据库迁移；首次建库或重置后请显式添加 `-RunMigrate`。
- `scripts/start_all.ps1` 与 `scripts/reset_data.ps1` 会在执行 `uv` 前自动清理外部 `VIRTUAL_ENV / CONDA_PREFIX / PYTHONHOME / PYTHONPATH`，并固定使用当前项目 `backend/.venv`。
- 若本地数据库仍来自旧迁移链，请先清理旧 schema，再执行 `cd backend; uv run alembic upgrade head`。
- 一键启动后可用以下命令做最小验收：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1
```

## 手动启动（仅排障）

### 1) 基础依赖

```powershell
.\infra\up.ps1
```

基础依赖包含：PostgreSQL、Redis、Etcd、MinIO、Milvus、SearXNG、Valkey。

SearXNG 常用入口：

- 配置页：`http://127.0.0.1:18080/config`
- 配置文件：`infra/searxng/config/settings.yml`
- 限流配置：`infra/searxng/config/limiter.toml`
- JSON Search API 示例：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:18080/search?q=OpenAI&format=json' -Headers @{ 'User-Agent'='Mozilla/5.0' }
```

若 `/config` 可访问但 `format=json` 无结果，优先检查 Podman 容器外网连通性或 `.env` 中的 `SEARXNG_HTTP_PROXY / SEARXNG_HTTPS_PROXY` 是否使用了容器可访问的代理地址。

### 2) 后端

```powershell
Set-Location .\backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop app.core.uvicorn_loop:windows_selector_loop_factory
```

- 手动排障时不要先激活其他 Python 虚拟环境；若当前终端已经激活，请先执行 `Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue` 与 `Remove-Item Env:CONDA_PREFIX -ErrorAction SilentlyContinue`。

- OpenAPI：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/api/v1/health`
- Windows 下不要省略 `--loop app.core.uvicorn_loop:windows_selector_loop_factory`；默认事件循环会触发 psycopg 启动失败。

### 3) Worker + Beat

```powershell
Set-Location .\backend
uv run celery -A app.worker.celery_app beat --loglevel=INFO
uv run celery -A app.worker.celery_app worker --loglevel=INFO -n worker.dispatch@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q dispatch
uv run celery -A app.worker.celery_app worker --loglevel=INFO -n worker.core@%h --pool=threads --concurrency=8 --prefetch-multiplier=1 -Q ingestion,rebuild,default
uv run celery -A app.worker.celery_app worker --loglevel=INFO -n worker.noncore@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q research,export
```

启动后可检查关键消费者是否在线：

```powershell
uv run celery -A app.worker.celery_app inspect active_queues -t 5
```

至少应看到 `default`、`dispatch`、`ingestion` 队列存在消费者。

### 4) 前端

```powershell
Set-Location .\frontend
npm install
npm run build
npm run start
```

## 重置本地数据（破坏性）

彻底清空本地 PostgreSQL、Milvus、Redis 与 SearXNG 本地持久化数据：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\reset_data.ps1 -Force
```

仅清理不迁移：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\reset_data.ps1 -Force -SkipMigrate
```

该脚本会：

- 执行 `podman compose down -v`
- 清理 `infra/data/redis`、`infra/data/milvus`、`infra/data/etcd`
- 清理 `infra/data/searxng`、`infra/data/searxng-valkey`
- 重启基础依赖
- 默认执行 `cd backend; uv run alembic upgrade head`

> ⚠️ 会删除本地数据库、向量库、Redis 与 SearXNG 持久化数据，请勿在共享环境直接执行。

## 当前配置要点

### 文档导入

- PDF 默认先走 MinerU pipeline；失败或输出为空时回退到 `pypdf` 文本提取。
- URL / DOCX / Markdown / TXT 保持原解析链路。
- 单文件上传上限为 `50MB`。
- 相关变量见 `.env.example`：`MINERU_*`、`PDF_FALLBACK_*`。

### Web 搜索

- 必填：`WEB_SEARCH_API_KEY`
- 可选搜索源：`SEARXNG_SEARCH_ENABLED`、`SEARXNG_BASE_URL`、`SEARXNG_TIMEOUT_SECONDS`
- 可选正文增强：`JINA_READ_ENABLED`、`JINA_READ_BASE_URL`、`JINA_READ_TIMEOUT_SECONDS`
- 其余超时、重试、默认深度参数见 `.env.example`

### KB Chat

- 仅支持内部工具（如 `kb_retrieve`），不加载 MCP 外接工具。
- 不支持两阶段工具审批，也不依赖 Human-in-the-loop。
- 预算与观测变量见 `.env.example`：`KB_CHAT_*`

## 文档入口

- 架构摘要：`docs/architecture.md`
- Research API 契约：`docs/api_contract_research.md`
- 快速验收脚本：`scripts/verify_quickstart.ps1`
