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
  "selected_kb_ids": [],
  "allow_external": true,
  "plan_first": true,
  "require_confirmation": true
}
```

响应：

- `session_id`
- `status`
- `plan_snapshot`（若 planner 已产生）

### 2. 确认研究计划

- `POST /api/v1/research/sessions/{session_id}/confirm-plan`

请求体：

```json
{
  "approved": true,
  "note": "继续执行"
}
```

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

当前 research artifacts 可能包含：

- `plan_snapshot`
- `research_brief`
- `source_bundle`
- `interim_findings`
- `interim_summary`
- `coverage_gaps`
- `report_json`
- `report_md`
- `metrics_snapshot`
- `gate_snapshot`

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

## 当前演示脚本

当前 demo 脚本：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\demo_research.ps1
```

仅校验脚本参数与流程时，可先执行：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\demo_research.ps1 -DryRun
```
