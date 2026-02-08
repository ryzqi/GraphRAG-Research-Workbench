# Multi-KB Agent System

This repository contains a graduation project codebase for a multi-knowledge-base agent system.
The primary docs are written in Chinese; the Chinese README starts below. This short English
preface exists mainly to keep the file ASCII-friendly for tooling and patching on Windows.

---

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

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 文档：`http://localhost:8000/docs`
- 健康检查：`GET http://localhost:8000/api/v1/health`

### 3) 启动 Worker（Celery）

```powershell
cd backend
uv run celery -A app.worker.celery_app worker --loglevel=INFO --pool=solo
```

### 4) 启动前端（Next.js App Router）

```powershell
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

## KB Chat 编排配置（KB_CHAT_*）

> 重要约束：KB Chat 仅支持内部工具（例如 `kb_retrieve`），不加载/不调用任何 MCP 外接工具（即使 `session.allow_external=true`）；同时 KB Chat 不支持“两阶段工具审批”（不会返回 `pending_tool_approval`），也不考虑终端/人工确认（Human-in-the-loop）。如需 MCP 工具/人工确认流程，请使用普通代理（General Chat）或 MCP 扩展页面。

- 预算（默认保守）：
  - `KB_CHAT_TOTAL_TIMEOUT_SECONDS=45`
  - `KB_CHAT_MAX_TOTAL_ROUNDS=3`
  - `KB_CHAT_MAX_RETRIEVAL_RETRIES=2`
  - `KB_CHAT_MAX_GENERATION_RETRIES=1`
  - `KB_CHAT_FORCE_RETRIEVE=true`（最终回答前至少检索一次；澄清等待阶段可先澄清）
- 查询增强：
  - `KB_CHAT_AMBIGUITY_CHECK_ENABLED=true`
  - `KB_CHAT_DECOMPOSITION_ENABLED=false`、`KB_CHAT_DECOMPOSITION_MAX_SUB_QUESTIONS=4`
  - `KB_CHAT_MULTI_QUERY_ENABLED=false`、`KB_CHAT_MULTI_QUERY_MAX_VARIANTS=4`
  - `KB_CHAT_HYDE_ENABLED=false`
- 观测：
  - `KB_CHAT_TRACE_ENABLED=true`

示例（放入 `.env`，非密钥项）：

```env
# KB Chat budgets
KB_CHAT_TOTAL_TIMEOUT_SECONDS=45
KB_CHAT_MAX_TOTAL_ROUNDS=3
KB_CHAT_MAX_RETRIEVAL_RETRIES=2
KB_CHAT_MAX_GENERATION_RETRIES=1
KB_CHAT_FORCE_RETRIEVE=true

# KB Chat query enhancement (optional)
KB_CHAT_AMBIGUITY_CHECK_ENABLED=true
KB_CHAT_DECOMPOSITION_ENABLED=false
KB_CHAT_DECOMPOSITION_MAX_SUB_QUESTIONS=4
KB_CHAT_MULTI_QUERY_ENABLED=false
KB_CHAT_MULTI_QUERY_MAX_VARIANTS=4
KB_CHAT_HYDE_ENABLED=false

# KB Chat observability
KB_CHAT_TRACE_ENABLED=true
```

