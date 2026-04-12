# 当前系统架构摘要

## 总体形态

当前仓库维持单体部署：

- frontend：Next.js / React
- backend：FastAPI
- async workers：Celery
- persistence：PostgreSQL / Redis / Milvus / MinIO

## Backend FastAPI 服务边界

当前 backend 已收敛为以下形状：

```text
route -> api/dependencies -> service -> repository/store -> database/integrations
```

### 已固定的边界

- `bootstrap/app_factory.py` 负责应用装配。
- `bootstrap/lifespan.py` 负责生命周期资源创建与释放。
- `bootstrap/app_resources.py` 统一管理 `engine`、HTTP clients、LLM client、Milvus、Redis 等运行时资源。
- `api/dependencies/app_resources.py` 是 API 侧读取应用资源的唯一入口。
- `api/dependencies/services.py` 是 API 侧 service provider 的唯一入口。
- `api/v1/endpoints/*` 只保留 HTTP 契约、参数解析、header 读取、streaming 响应映射，不再手工 `new Service(...)`，也不再直接读取 `request.app.state.*`。

### 当前已提炼的 repository

- `repositories/research_session_repository.py`
  - 负责 `research_sessions` 聚合读取与基础持久化挂接。
- `repositories/extension_repository.py`
  - 负责 `tool_extensions` 的查询、分页、读取与删除。
- `repositories/queue_health_repository.py`
  - 负责 queue health 相关的数据库统计查询。

### 当前保留在 service 的职责

- service 仍拥有 orchestration、校验后的流程分支、外部集成协调与事务提交决策。
- `ResearchArtifactStore`、`ResearchEventStore` 继续作为 research 域专用存储抽象。

### 当前明确不做

- 不做全仓 `domain/`、`use_cases/`、`ports/` 的完整迁移。
- 不为旧装配方式保留兼容层。
- 不改变任何现有 HTTP 契约、状态码与业务语义。

## Research 当前主路径

Deep Research 当前采用单路径会话化架构：

1. `POST /api/v1/research/sessions`
2. LLM scoper 判断是否需要 `clarification_request`
3. 若信息足够则直接产出 `plan_snapshot` / `research_brief` 并进入 runtime
4. 若信息不足则先走 `POST /clarification`，补充后直接进入 runtime
5. runtime 执行并写入 `research_events` / `research_artifacts`
6. `POST /interrupt` / `POST /resume`
7. finalizer 产出 `report_md` / `report_json`
8. `GET /artifacts` 读取最终工件与 observability 工件

## Research 事实源

当前 research 业务事实源只有三张表：

- `research_sessions`
- `research_events`
- `research_artifacts`

当前对外主标识只有：

- `session_id`

不保留旧 `/api/v1/research/runs*` 与 run-centric 兼容层。

## Research runtime 边界

- runtime harness：Deep Agents `create_deep_agent`
- stream contract：`subgraphs=True` + `version="v2"`
- source providers：Tavily / Jina Reader(`r.jina.ai`) / SearXNG / arXiv
- non-goal：research mode 不接 MCP

## Research 可观测与门禁

当前 research artifacts 除 `report_md` / `report_json` 外，还补充：

- `metrics_snapshot`
- `gate_snapshot`

当前事件封套保留：

- `trace_id`
- `phase`
- `namespace`
- `lc_agent_name`
- `source_provider`

默认 release gate：

- `RESEARCH_GATE_MIN_QUALITY_SCORE=0.75`
- `RESEARCH_GATE_MAX_P95_MS=120000`
- `RESEARCH_GATE_MAX_SESSION_COST_USD=2.0`

## 文档入口

- research 合同：`docs/api_contract_research.md`
- research 重构 proposal：`full-refactor-deep-research/proposal.md`
- research 设计：`full-refactor-deep-research/design.md`
- rollback runbook：`full-refactor-deep-research/research-rollback-runbook.md`
- demo script：`scripts/demo_research.ps1`
