# 多知识库 + 多智能体协作知识代理系统

本仓库为毕业设计代码与演示脚手架，目标是实现：多知识库隔离与联合检索、可追溯证据清单、多智能体协作、深度研究与导出复现。

## 仓库结构

- `frontend/`：Next.js 前端。
- `backend/`：FastAPI、Celery、数据接入与研究运行时。
- `infra/`：Podman 基础设施、SearXNG 配置与本地数据目录。
- `scripts/`：启动、验收与公共辅助脚本。
- `docs/`：架构、API 契约与运维配置文档。

## Deep Research 当前事实源

- 统一业务主标识：`session_id`
- 统一公开前缀：`/api/v1/research/sessions*`
- 统一工件读取：`research_artifacts`
- 最终报告：`report_md` / `report_json`
- 可观测工件：`metrics_snapshot` / `gate_snapshot`
- 前端展示优先消费：`presentation_snapshot`
- 详细契约：`docs/api_contract_research.md`

## 模型配置

- 运行时模型主配置（供应商、Base URL、API Key、模型列表、全局生效模型）通过前端「模型配置」页面维护。
- `.env` 用于 deploy config、Embedding、Web 搜索与公开地址；不再作为运行时 LLM 主配置表。
- `llama.cpp` provider 支持填写 `http://<llama-cpp-host>:8080`、`/v1` 或完整 `/v1/chat/completions`；保存时会规范化为 `/v1`。

## 环境要求

- Windows 11
- Python 3.13+
- Node.js `^20.19.0 || >=22.12.0`
- `uv`
- Podman（建议 Podman Desktop；`podman-compose` 仅作为回退方式）

## 本地开发

### 1. 准备配置

1. 复制 `.env.example` 为 `.env`，补齐至少以下值：
   - `NEXT_PUBLIC_API_BASE_URL`
   - `BACKEND_PUBLIC_BASE_URL`
   - `FRONTEND_PUBLIC_BASE_URL`
   - `CORE__DATABASE_URL`
   - `STORAGE__MINIO_*`
   - `CORE__EMBEDDING_*`
2. 如需覆盖本地基础设施变量，复制 `infra/env/dev.env.example` 为 `infra/env/dev.env` 再修改。

### 2. 一键启动

以下脚本仅面向 Windows 本地开发，不作为生产部署入口：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

常用参数：

- `-SkipInfra`
- `-NoDetachInfra`
- `-SkipBackend`
- `-SkipWorker`
- `-SkipFrontend`
- `-RunMigrate`
- `-Verbose`

补充说明：

- 默认跳过数据库迁移；首次建库或重置后请显式添加 `-RunMigrate`。
- `scripts/start_all.ps1` 会在执行 `uv` 前自动清理外部 `VIRTUAL_ENV / CONDA_PREFIX / PYTHONHOME / PYTHONPATH`，并固定使用当前项目 `backend/.venv`。
- 若本地数据库仍来自旧迁移链，请先清理旧 schema，再执行 `uv run alembic upgrade head`。

### 3. 本地验收

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1 -SkipInfra
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1
```

## 手动本地启动（仅排障）

### 基础依赖

```powershell
pwsh -ExecutionPolicy Bypass -File .\infra\up.ps1
```

基础依赖包含：PostgreSQL、Redis、Etcd、MinIO、Milvus、SearXNG、Valkey。

### 后端

```powershell
Set-Location .\backend
uv sync
uv run uvicorn app.main:app --host $env:BACKEND_BIND_HOST --port $env:BACKEND_PORT --loop app.core.uvicorn_loop:windows_selector_loop_factory
```

说明：

- `BACKEND_BIND_HOST` 与 `BACKEND_PORT` 由 `.env` 提供；未设置时脚本默认使用 `0.0.0.0` 与 `8000`。
- OpenAPI 与健康检查请以 `.env` 中的 `BACKEND_PUBLIC_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` 为准。

### Worker + Beat

```powershell
Set-Location .\backend
uv run celery -A app.worker.celery_app beat --loglevel=INFO
uv run celery -A app.worker.celery_app worker --loglevel=INFO -n worker.dispatch@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q dispatch
uv run celery -A app.worker.celery_app worker --loglevel=INFO -n worker.core@%h --pool=threads --concurrency=8 --prefetch-multiplier=1 -Q ingestion,rebuild,default
uv run celery -A app.worker.celery_app worker --loglevel=INFO -n worker.noncore@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q research,export
```

### 前端

```powershell
Set-Location .\frontend
npm install
npm run build
npm run start -- --port $env:FRONTEND_PORT
```

## 生产配置与 Secrets

- 生产部署请使用：
  - `infra/podman-compose.base.yml`
  - `infra/podman-compose.prod.example.yml`
  - `infra/env/prod.env.example`
- 详细运行手册、Secrets 注入方式、迁移顺序与回滚策略见：
  - `docs/ops/config-and-secrets.md`

关键原则：

- feature flags 不是 secrets manager
- `NEXT_PUBLIC_*` 只承载浏览器可见配置，不承载 secrets
- 默认口令、宿主机代理 IP、loopback URL 不进入共享模板

## 当前配置要点

### 文档导入

- PDF 默认先走 MinerU pipeline；失败或输出为空时回退到 `pypdf` 文本提取。
- URL / DOCX / Markdown / TXT 保持原解析链路。
- 单文件上传上限为 `50MB`。

### Web 搜索

- 必填：`WEB_SEARCH_API_KEY`
- 可选搜索源：`SEARXNG_SEARCH_ENABLED`、`WEB_SEARCH__SEARXNG_SEARCH_BASE_URL`
- 可选正文增强：`JINA_READ_ENABLED`、`JINA_READ_BASE_URL`

### KB Chat

- 仅支持内部工具（如 `kb_retrieve`），不加载 MCP 外接工具。
- 不支持两阶段工具审批，也不依赖 Human-in-the-loop。

## 文档入口

- 架构摘要：`docs/architecture.md`
- Research API 契约：`docs/api_contract_research.md`
- 运维与 Secrets：`docs/ops/config-and-secrets.md`
- 硬编码审计：`docs/hardcoded_audit_2026-04-13.md`
