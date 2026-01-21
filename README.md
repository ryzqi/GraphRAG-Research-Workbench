# 多知识库 + 多智能体协作知识代理系统

本仓库为毕业设计代码与演示脚手架，目标是实现：多知识库隔离与联合检索、可追溯证据清单、多智能体协作/深度研究、对比评测与导出复现。

- 规格与设计文档：`specs/001-multi-kb-agent-collab/`
- 快速开始（强烈建议先读）：`specs/001-multi-kb-agent-collab/quickstart.md`
- API 契约（OpenAPI）：`specs/001-multi-kb-agent-collab/contracts/openapi.yaml`

## 功能与导航

- 根路径 `/` 默认进入普通代理。
- 顶部导航顺序：普通代理 → 知识库问答 → 知识库管理 → 深度研究 → MCP扩展 → 对比评测。
- 反馈功能已移除。

## 先决条件

- **操作系统**：Windows 11
- **Python**：3.13+
- **Node.js**：20+
- **uv**：Python 包管理器（用于后端依赖）
- **Podman**：容器运行时（建议安装 Podman Desktop）
- **podman-compose**：容器编排工具（`pip install podman-compose`）

## 本地运行（Windows）

### 一键启动（推荐）

- 复制 `.env.example` 为 `.env` 并按需修改后，在仓库根目录执行：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

- 可选参数：`-SkipInfra`（跳过 Podman 依赖）、`-NoDetachInfra`（前台启动依赖）、`-SkipBackend`、`-SkipWorker`、`-SkipFrontend`、`-SkipMigrate`、`-RunSeed`（导入演示数据）、`-Verbose`。

### 1) 启动基础依赖（Podman）

- 复制 `.env.example` 为 `.env` 并按需修改
- 在仓库根目录运行：

```powershell
.\infra\up.ps1
```

> **注意**：若 `up.ps1` 脚本报错，可直接运行：
>
> ```powershell
> cd infra
> podman-compose up -d
> ```

> **端口冲突**：若本地已安装 PostgreSQL 占用 5432 端口，需在 `.env` 中将 `POSTGRES_PORT` 改为 `5433`，并同步修改 `DATABASE_URL` 和 `MEMORY_STORE_URL` 中的端口。

### 2) 启动后端（FastAPI）

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 文档：`http://localhost:8000/docs`
- 健康检查：`GET http://localhost:8000/api/v1/health`

### 3) 启动 Worker（Celery）

```bash
cd backend
uv run celery -A app.worker.celery_app worker --loglevel=INFO --pool=solo
```

### 4) 启动前端（React + Vite）

```bash
cd frontend
npm install
npm run dev
```

## Web 搜索（Tavily）配置
- 必填：`WEB_SEARCH_API_KEY`
- 常用参数：`WEB_SEARCH_DEFAULT_SEARCH_DEPTH`、`WEB_SEARCH_DEFAULT_TIME_RANGE`、`WEB_SEARCH_DEFAULT_MAX_RESULTS`
- 策略开关：`WEB_SEARCH_AUTO_PARAMETERS`、`WEB_SEARCH_INCLUDE_USAGE`
- 可靠性：`WEB_SEARCH_TIMEOUT_SECONDS`、`WEB_SEARCH_RETRY_MAX`、`WEB_SEARCH_RATE_LIMIT_PER_MINUTE`
- 深度工具默认值：`WEB_EXTRACT_DEFAULT_DEPTH`、`WEB_CRAWL_DEFAULT_*`
- 研究输出：`WEB_RESEARCH_OUTPUT_FORMAT`、`WEB_RESEARCH_CITATION_FORMAT`、`WEB_RESEARCH_TIMEOUT_SECONDS`
