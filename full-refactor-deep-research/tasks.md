## 0. 并行执行分组与同步里程碑

- [ ] 0.1 建立并行分组：A 组（planner + runtime + persistence）、B 组（API + SSE + artifacts）、C 组（frontend service + workbench）、D 组（observability + eval + rollback）。
- [ ] 0.2 定义跨组阻塞关系：A 输出研究契约与工件结构后，B/C 才可联调；A+B+C 完成主路径后，D 才执行门禁。
- [ ] 0.3 设立同步检查点：`M1: preflight planner + session`、`M2: runtime + stream + finalizer`、`M3: current endpoint integration + gate`。
- [ ] 0.4 为检查点落地验收记录模板（负责人、输入版本、结果、遗留问题、下一步）。

## 1. 研究域模型与迁移

- [ ] 1.1 新建 `ResearchSession`、`ResearchEvent`、`ResearchArtifact` 三个模型文件并定义关键字段。
- [ ] 1.2 为 `research_sessions` 增加状态机字段、`thread_id`、planner/runtime/finalizer 阶段字段与必要索引。
- [ ] 1.3 为 `research_events` 增加 `event_id`、`sequence`、`event_type`、`trace_id`、`idempotency_key`、`namespace` 字段，并落地 `(session_id, sequence)` 与 `(session_id, event_id)` 唯一约束。
- [ ] 1.4 在 `backend/src/app/db/base.py` 注册新模型并创建 Alembic 迁移。
- [ ] 1.5 补充 `backend/tests/research/test_models_runtime_schema.py`，验证唯一键、终态不可逆、线程标识与 namespace 存储约束。

## 2. 契约、事件封套与恢复协议

- [ ] 2.1 新建 `backend/src/app/schemas/research.py`，定义 create session、plan snapshot、confirmation、event envelope、interrupt/resume、artifacts 契约。
- [ ] 2.2 冻结最小事件字段：`event_id`、`sequence`、`timestamp`、`event_type`、`session_id`、`phase`、`namespace`、`payload`、`trace_id`。
- [ ] 2.3 定义流恢复参数：`Last-Event-ID`（续流优先）与 `resume_from_event_id`（显式恢复控制）。
- [ ] 2.4 在恢复契约中定义 `idempotency_key` 与重复请求一致性语义。
- [ ] 2.5 扩展 plan / citation schema：支持 `research_brief`、`target_sources=kb|web|paper|hybrid`、`source_type`、`source_provider`、`retrieval_method`、`source_id`、`origin_url`、`arxiv_id`、`authors`、`published_at`、`pdf_url` 等字段。
- [ ] 2.6 为字段约束与默认值编写 `backend/tests/research/test_schemas_research.py`。

## 3. Preflight Planner

- [ ] 3.1 新建 `backend/src/app/services/research_planner.py` 与 `research_planner_types.py`，实现轻量 preflight planner。
- [ ] 3.2 让 planner 只产出 `research_brief`、复杂度、子任务、`target_sources`、预算提示、计划摘要与确认需求，不执行正式外部研究。
- [ ] 3.3 设计 planner 的 auto-approve / confirmation_required 规则，并持久化 `plan_snapshot`。
- [ ] 3.4 编写 `backend/tests/research/test_research_planner.py`，覆盖 simple / comparative / complex 三类规划结果。

## 4. DeepAgents 单引擎运行时

- [ ] 4.1 新建 `deep_research_runtime.py` 与 `research_runtime_types.py`，统一封装 `create_deep_agent` 运行时构建。
- [ ] 4.2 在工具注册层增加“研究模式无 MCP”装配函数，并确保深度研究默认同时装配 Tavily、Jina Reader、SearXNG、arXiv 四类 provider。
- [ ] 4.3 对齐当前 DeepAgents 中间件栈（TodoList / Filesystem / SubAgent / Summarization / PatchToolCalls），并在需要时启用 Memory / Skills / HITL。
- [ ] 4.4 显式配置 `checkpointer`、`thread_id` 映射、`subagent_model`、`interrupt_on` 与大结果落盘策略。
- [ ] 4.5 实现 `CompositeBackend` 分层路由：`/workspace|/scratch|/plans -> StateBackend`，`/memories|/skills -> StoreBackend`；预置 `AGENTS.md` 与技能目录。
- [ ] 4.6 若研究需要执行命令，选型并接入官方 sandbox backend；禁止生产使用 `LocalShellBackend`。
- [ ] 4.7 编写 `backend/tests/research/test_deep_research_runtime.py`，验证单入口、禁用 MCP、中间件装配、后端分层、落盘策略、主/子代理模型分层与恢复配置。

## 5. Source-aware Routing、子代理与 Finalizer

- [ ] 5.1 启用 Tavily 全功能工具族：`tavily_search`、`tavily_extract`、`tavily_crawl`、`tavily_research`，并在研究模式默认全部可用。
- [ ] 5.2 新增 Jina Reader 工具：`jina_read`（基于 `r.jina.ai`），并统一处理原始 URL 回写。
- [ ] 5.3 新增 `searxng_search` 工具，基于受控 SearXNG Search API 调用并支持 JSON 响应、类别/时间范围/引擎筛选。
- [ ] 5.4 新增 `arxiv_search` / `arxiv_fetch` 工具，基于 Python `arxiv` 库 direct 调用 arXiv API。
- [ ] 5.5 为 runtime 建立 `general-purpose` 默认子代理与最少数 source-specialized subagents（`kb`、`web`、`paper`、`citation`）。
- [ ] 5.6 在 planner/runtime 中落实 source routing：`paper` 任务优先 arXiv；`web` 任务按策略组合调用 Tavily / Jina Reader / SearXNG；`hybrid` 先建论文基线再补网页上下文。
- [ ] 5.7 实现 KB / Tavily / Jina Reader / SearXNG / arXiv 证据 canonicalization、dedup 与 `source_bundle` 中间收口，并显式产出 `interim_summary`、`coverage_gaps`。
- [ ] 5.8 新建 `research_finalizer.py`，将 findings / source bundles 收口为 canonical citations、`report_json` 与 `report_md`。
- [ ] 5.9 让 `response_format` 仅在 finalizer 阶段承担结构化约束，并将 `structured_response` 持久化为 `report_json`。
- [ ] 5.10 扩展 `backend/tests/research/test_deep_research_runtime.py`，覆盖 Tavily 全功能、Jina Reader、SearXNG、纯网页、纯论文、混合来源、plan preview、subagent delegation、namespace streaming 与 finalizer。

## 6. 研究会话编排与持久化服务

- [x] 6.1 实现 `ResearchEventStore` 的 append-only 写入、序号递增与 `event_id` 幂等写入。
- [x] 6.2 实现 `ResearchArtifactStore`，打通 `plan_snapshot`、`research_brief`、中间 findings、`source_bundle`、`interim_summary`、`coverage_gaps`、最终工件更新，并持久化 `source_provider` / `retrieval_method` / `origin_url`。
- [x] 6.3 实现 `ResearchService`，串起 create session、planner、confirm、runtime、finalizer、interrupt/resume。
- [x] 6.4 实现恢复请求幂等与并发冲突处理，确保 `sequence` 连续与状态迁移合法。
- [x] 6.5 编写 `backend/tests/research/test_research_service.py`，验证事件顺序、planner -> runtime -> finalizer 转换、幂等恢复与工件产出。

## 7. 当前端点集合与 Worker 集成

- [x] 7.1 新建 `backend/src/app/api/v1/endpoints/research.py`，定义当前研究会话接口。
- [x] 7.2 在 `backend/src/app/api/v1/api.py` 接入研究 router，并明确 `/api/v1` 为当前公开研究命名空间。
- [x] 7.3 设计当前端点集合：`POST /api/v1/research/sessions`、`POST /api/v1/research/sessions/{session_id}/confirm-plan`、`GET /api/v1/research/sessions/{session_id}/stream`、`POST /api/v1/research/sessions/{session_id}/interrupt`、`POST /api/v1/research/sessions/{session_id}/resume`、`GET /api/v1/research/sessions/{session_id}/artifacts`。
- [x] 7.4 重写 `backend/src/app/worker/tasks/research.py`，使其只调用 `ResearchService`。
- [x] 7.5 将 SSE 映射统一建立在当前 graph stream contract 的 `GraphOutput` / `StreamPart` 结构之上，并保留 `namespace` / `subagent_name` / `phase` / `source_provider`。
- [x] 7.6 编写 `backend/tests/api/test_research_endpoints.py`，覆盖 create / confirm-plan / stream / interrupt / resume / artifacts 全流程。
- [x] 7.7 调整 `backend/tests/test_backend_research_removal_contract.py` 或等价测试，明确研究接口已按当前路由集合重新接入。

## 8. 导出链路与工件读取

- [x] 8.1 重构 `research_exporter.py`，直接从 `research_artifacts` 读取 `report_md` 与 `report_json`。
- [x] 8.2 更新 `worker/tasks/export.py` 与 `export_service.py`，统一按 `session_id` 读取研究工件。
- [x] 8.3 缺失关键工件时返回结构化错误码（如 `ARTIFACT_INCOMPLETE`）并记录诊断信息。
- [x] 8.4 编写 `backend/tests/research/test_research_exporter.py`，覆盖双产物成功与缺失工件失败场景。

## 9. 前端数据层直接改造当前研究服务

- [x] 9.1 直接改造 `frontend/src/services/research.ts`，切到 `session_id` 驱动的研究会话契约。
- [x] 9.2 新建 `frontend/src/types/researchEvents.ts` 与 `frontend/src/hooks/queries/useResearch.ts`，保持单服务文件入口。
- [x] 9.3 让当前研究服务直接请求当前研究端点集合。
- [x] 9.4 实现统一流消费器：按 `event_id` 去重、按 `sequence` 重排、支持小窗口乱序容忍，并保留 `namespace` 与 `source_provider` 以分流主/子代理事件和 provider 事件。
- [x] 9.5 实现断线重连恢复策略（优先 `Last-Event-ID`，失败回退快照 + 增量流）。
- [x] 9.6 通过 `npm run typecheck` 验证当前研究服务与事件类型约束。

## 10. 前端事件驱动研究工作台

- [ ] 10.1 新建 `ResearchTimeline`、`PlanPreviewPanel`、`InterruptDecisionPanel`、`ArtifactPanel` 核心组件。
- [ ] 10.2 重构研究页面，接入 `research_brief`、来源路由摘要、namespace-aware 时间线、中断决策与双工件展示，并展示 Tavily / Jina Reader / SearXNG / arXiv provider 维度。
- [ ] 10.3 为网页证据与论文证据增加差异化展示（标题、作者、发布日期、arXiv / PDF 链接），并对网页证据展示 `source_provider` 与 `origin_url`。
- [ ] 10.4 实现 Markdown / JSON 安全渲染策略。
- [ ] 10.5 在 timeline 中展示主代理 phase 与子代理 namespace 进度，并完成一次 planner -> confirm -> runtime -> interrupt -> resume -> final 联调验收。

## 11. 可观测、评测与故障注入

- [ ] 11.1 打通 `trace_id` / `session_id` / `lc_agent_name` / `namespace` 关联，形成端到端 tracing。
- [ ] 11.2 采集质量、延迟、成本三类核心指标，并拆分 `kb/web/paper/hybrid` 来源通道、`source_provider` 维度与主/子代理模型层级。
- [ ] 11.3 建立研究评测基线与默认门禁阈值（`RESEARCH_GATE_*`）。
- [ ] 11.4 新增故障注入测试（数据库抖动、Redis 不可用、Tavily / Jina Reader / SearXNG / arXiv 超时、429、实例不可达与响应格式异常）。
- [ ] 11.5 新增事件回放测试，验证同一会话回放与终态一致性。
- [ ] 11.6 编写回滚演练脚本与操作手册，并输出演练记录。
- [ ] 11.7 新增 `backend/tests/research/test_e2e_interrupt_resume_contract.py`，验证中断恢复到 final 的契约闭环。

## 12. 文档与契约同步

- [ ] 12.1 更新 `proposal.md`、`design.md`、`specs/*/spec.md` 与 `tasks.md`，统一为当前研究单路径术语。
- [ ] 12.2 更新 `README.md`、`docs/architecture.md` 并新增 `docs/api_contract_research.md`。
- [ ] 12.3 在契约文档中明确当前研究端点集合、事件封套、planner/runtime/finalizer 阶段边界、namespace streaming、`source_provider` 语义与错误码。
- [ ] 12.4 编写 `scripts/demo_research.ps1`，覆盖 create session、plan preview、confirm、stream、interrupt、resume、final 全流程。

## 13. 最终验证与交付门禁

- [ ] 13.1 执行 `cd backend; uv run pytest` 与 `uv run ruff check .`。
- [ ] 13.2 执行 `cd frontend; npm run typecheck` 与 `npm run build`。
- [ ] 13.3 执行 `pwsh -ExecutionPolicy Bypass -File scripts/demo_research.ps1`，确认 planner、runtime、finalizer 与工件链路正常。
- [ ] 13.4 汇总质量 / 延迟 / 成本 / 韧性 / 来源覆盖门禁结果并形成发布决议记录。
- [ ] 13.5 复核文档中统一使用当前研究单路径术语。
