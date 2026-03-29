# 当前系统架构摘要

## 总体形态

当前仓库维持单体部署：

- frontend：Next.js / React
- backend：FastAPI
- async workers：Celery
- persistence：PostgreSQL / Redis / Milvus / MinIO

## Research 当前主路径

Deep Research 当前采用单路径会话化架构：

1. `POST /api/v1/research/sessions`
2. preflight planner 产出 `plan_snapshot` / `research_brief`
3. `POST /confirm-plan`
4. runtime 执行并写入 `research_events` / `research_artifacts`
5. `POST /interrupt` / `POST /resume`
6. finalizer 产出 `report_md` / `report_json`
7. `GET /artifacts` 读取最终工件与 observability 工件

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
