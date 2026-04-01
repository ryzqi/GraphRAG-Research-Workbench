# 当前 Research API Contract

## 范围

本文档只描述当前对外公开的 Deep Research 单路径契约：

- 统一主标识：`session_id`
- 统一公开前缀：`/api/v1/research/sessions*`
- 统一工件读取：`research_artifacts`
- 统一门禁工件：`metrics_snapshot` / `gate_snapshot`

不包含旧 `/api/v1/research/runs*`；也不包含任何 run-centric 兼容层。

## 当前端点集合

### 1. 创建研究会话

- `POST /api/v1/research/sessions`

请求体：

```json
{
  "question": "比较 Tavily、Jina Reader 与 SearXNG 在当前 research 工作台中的定位",
  "plan_first": true
}
```

响应：

- `session_id`
- `status`
- `status=clarifying` 时返回 `clarification_request`
- `status=queued` 时返回 `plan_snapshot`

说明：

- `plan_first` 固定为 `true`，当前公开契约只支持 clarification-first / plan-first 路径。
- 创建会话会先进入 LLM scoping；若信息足够则直接返回 `queued` 并开始研究，若不足则返回 `clarifying`。

### 2. 提交澄清回答

- `POST /api/v1/research/sessions/{session_id}/clarification`

请求体：

```json
{
  "answer": "关注 LangGraph StateGraph 入门、适用边界与迁移建议"
}
```

响应：

- 若信息仍不足：`status=clarifying` + `clarification_request`
- 若已可生成计划：`status=queued` + `plan_snapshot`

说明：

- 当前链路不再暴露人工确认计划接口。
- `plan_snapshot` 仍会返回并持久化，但只作为研究前计划展示与审计工件，不再阻塞执行。

### 3. 读取研究事件流

- `GET /api/v1/research/sessions/{session_id}/stream`

支持：

- `Last-Event-ID`：优先续流游标
- `resume_from_event_id`：显式恢复游标

### 4. 中断研究

- `POST /api/v1/research/sessions/{session_id}/interrupt`

请求体：

```json
{
  "reason": "等待人工确认"
}
```

### 5. 恢复研究

- `POST /api/v1/research/sessions/{session_id}/resume`

请求体：

```json
{
  "idempotency_key": "resume-demo-001",
  "resume_from_event_id": "evt-000123",
  "decisions": [
    {
      "action": "approve",
      "scope": "research"
    }
  ]
}
```

### 6. 读取研究工件

- `GET /api/v1/research/sessions/{session_id}/artifacts`

## 事件封套

当前 Research SSE 事件封套最小字段：

- `event_id`
- `sequence`
- `timestamp`
- `event_type`
- `session_id`
- `phase`
- `namespace`
- `payload`
- `trace_id`
- `lc_agent_name`

可选辅助字段：

- `subagent_name`
- `source_provider`
- `retrieval_method`
- `origin_url`

### 当前关键事件族

- `research.plan.*`
- `research.run.*`
- `research.finalizer.*`
- `research.trace.recorded`

失败路径补充：

- `research.run.failed`

## 当前工件键

当前 Deep Research OS artifacts 不再只包含旧的计划 / 报告列表，而是按阶段扩展为以下键集合：

### 规划 / 澄清阶段

- `clarification_request`
- `clarification_answer`
- `plan_snapshot`
- `research_brief`

### workspace bootstrap

- `mission_md`
- `plan_md`
- `query_map_md`
- `coverage_md`
- `report_draft_md`

### runtime / finalizer 产物

- `source_bundle`
- `interim_findings`
- `interim_summary`
- `coverage_gaps`
- `report_json`
- `report_md`

### verification / ledger 产物

- `claim_map_json`
- `coverage_matrix_json`
- `conflicts_json`
- `source_ledger_json`

### observability / gate 产物

- `metrics_snapshot`
- `gate_snapshot`

说明：

- `mission_md` / `plan_md` / `query_map_md` / `coverage_md` / `report_draft_md` 为 workspace bootstrap 工件，用于工作台主阅读区与 scratch 路径对齐。
- `claim_map_json` / `coverage_matrix_json` / `conflicts_json` / `source_ledger_json` 为 finalizer verification ledger，供前端 evidence / claims / conflicts 展示与导出使用。
- 对外读取入口仍统一为 `GET /api/v1/research/sessions/{session_id}/artifacts`，客户端按 `artifact_key` 分派。

### `metrics_snapshot`

当前会话的 observability / replay / provider / model 统计，至少覆盖：

- trace：`trace_id` / `session_id` / `thread_id` / `links`
- quality：`score` / `citation_count` / `finding_count`
- latency：`runtime_latency_ms` / `session_latency_ms` / `p95_ms`
- cost：`session_cost_usd`
- providers：按 `source_provider` 维度拆分
- models：按 `layer` 与 `lc_agent_name` 拆分
- replay：回放一致性结果
- faults：失败分类与 provider 归因

### `gate_snapshot`

当前 release gate 结果，至少覆盖：

- `pass`
- `violations`
- `thresholds`
- `scores`

默认阈值：

- `RESEARCH_GATE_MIN_QUALITY_SCORE=0.75`
- `RESEARCH_GATE_MAX_P95_MS=120000`
- `RESEARCH_GATE_MAX_SESSION_COST_USD=2.0`

## 当前错误码

当前已落地的研究相关错误码包括：

- `RESEARCH_SESSION_NOT_FOUND`
- `RESEARCH_PLAN_SNAPSHOT_MISSING`
- `RESEARCH_ARTIFACT_MISSING`
- `ARTIFACT_INCOMPLETE`

## 当前 smoke 脚本

当前最小 smoke 入口：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\smoke_research_os.ps1
```

该脚本只串联：

- backend：`uv run pytest tests\research\test_deep_research_runtime_runner.py tests\research\test_research_service.py -q`
- frontend：`npx vitest run src\views\ResearchPage.test.tsx src\services\researchWorkbench.test.ts`
