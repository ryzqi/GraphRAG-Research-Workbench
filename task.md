# KB Chat LangGraph 状态/持久化/可观测修复实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 KB Chat 在 LangGraph State、节点输入输出、路由、checkpoint 恢复、同线程并发、跨线程记忆命名空间、SSE 协议和前端 trace 消费上的结构性问题，消除状态污染与协议漂移，使其满足生产环境的正确性、可观测性和多用户安全要求。

**Architecture:** 采用“输入/输出/内部状态分层 + runtime.context 承载运行时不变量 + 线程级 checkpoint / 用户级 store 显式分离 + `Command(goto=...)` 单一路由真值 + summary-first 流式观测协议”的改造路线。先封堵 P0 状态污染与恢复错误，再瘦身 State 和路由契约，最后补齐重试缓存、SSE 心跳、前后端 trace 对齐和灰度发布门禁。

**Tech Stack:** Python 3.13, FastAPI, LangGraph StateGraph/Runtime/Checkpointer/Store, LangChain, AsyncPostgresSaver, AsyncPostgresStore, React, TypeScript, SSE.

---

## 0. 最新 LangGraph 用法约束（2026-03-13 已核对）

以下约束直接决定本次修复方案，执行时不得逆着框架语义做补丁：

- `StateGraph` 的 reducer 字段是“累加/合并”语义，不是“覆盖”语义；对 reducer 字段写入 `[]` 不会清空历史，而是参与 reducer 合并。
- LangGraph 支持 `input_schema` / `output_schema` / 内部共享 state 分离；对中间态应优先用“私有状态”而不是把所有 scratch 字段暴露到全局共享 state。
- 运行时不变量（`user_id`、`thread_id`、`runtime_config`、store 访问）应优先经 `context_schema` / `Runtime.context` / `Runtime.store` 传递，而不是在可持久化 state 中反复复制。
- checkpoint 是按 `thread_id` 保存的；`update_state` 和 checkpoint 恢复也会遵守 reducer 语义，因此恢复逻辑不能把 reducer 字段当作普通覆盖字段使用。
- 子图默认继承父图 checkpointer；不应在每个子图单独做持久化拼接。
- streaming 支持 `messages` / `updates` / `custom`；自定义事件必须有明确消费方，且应与 envelope 校验/降级策略配套。
- `retry_policy` 和 node cache 应在 `add_node(...)` / `compile(...)` 层面明确挂载；保留但不启用的“伪能力”要么落地，要么删除。

**参考链接（执行修复时继续以官方文档为准）：**

- Graph API / reducers / input-output schema / private state  
  https://langchain-ai.github.io/langgraph/how-tos/graph-api/
- Runtime / `Runtime.context` / `Runtime.store` / `stream_writer`  
  https://langchain-ai.github.io/langgraph/reference/runtime/
- Persistence / threads / checkpoints / pending writes  
  https://docs.langchain.com/oss/python/langgraph/persistence#threads
- Subgraph checkpointer propagation  
  https://langchain-ai.github.io/langgraph/how-tos/memory/add-memory/#use-in-subgraphs
- Streaming modes (`messages` / `updates` / `custom`)  
  https://docs.langchain.com/langgraph-platform/streaming?codeTab=Python#supported-stream-modes

---

## 1. 本计划覆盖范围

### In Scope

- KB Chat LangGraph 主图、子图、State、节点输入输出、节点间跳转。
- checkpoint 恢复、thread 持久化、memory store 命名空间。
- 同线程并发保护、重试/缓存策略、SSE 流式协议与 trace 可观测。
- 前端 trace schema、节点目录、node_io/custom 事件消费闭环。
- 与上述变更直接相关的测试、文档、灰度/回滚与验收脚本。

### Out of Scope

- 不改 Retrieval 算法本身（dense/sparse/rerank 召回质量）；
- 不改 KB Chat 产品交互文案和页面视觉设计；
- 不重做整个 agent 框架；
- 本轮不引入新的第三方可观测平台，只做现有日志/SSE/trace 协议收敛；
- 当前文件仅写计划，不在本轮直接改业务代码。

---

## 2. 问题清单与优先级

| 优先级 | 问题 | 风险 |
| --- | --- | --- |
| P0 | `subquery_runs` / `answer_review_runs` 使用 additive reducer，却试图用 `[]` 清空 | 跨轮次污染、错误融合、错误 UI trace |
| P0 | fresh turn state 先构造再被 checkpoint `channel_values` 整体覆盖 | 旧 `user_input/messages/loop_counts/reflection/...` 泄漏到新轮次 |
| P1 | State 过宽且语义重复：`display_context/merged_context`、`compressed_context/final_context`、`doc_gate_state/reflection`、`answer_quality/reflection`、`runtime_config` | 维护成本高、检查点恢复含混、trace 字段重复 |
| P1 | 路由真值重复：`Command(goto)`、`preprocess_next`、`reflection.action`、`stage_summaries.*.goto/decision` | 路由判断分叉，修一处漏三处 |
| P1 | 缺同 thread single-flight 保护 | 同一会话并发运行时 checkpoint 竞争、结果错乱 |
| P1 | `user_id="local"` 硬编码 | 多用户命名空间冲突、memory 污染 |
| P2 | retry/cache 能力存在但未真正生效 | 瞬时故障恢复差、死代码存在 |
| P2 | `node_io` 发射完整 `input_snapshot/output_snapshot` | 负载过重、隐私风险、SSE 容易膨胀 |
| P2 | 协议漂移降级不足 | event 缺字段时只能计数或丢弃，前后端兼容性弱 |
| P2 | 后端发 `custom` 审查事件，前端不消费 | 观测信息丢失 |
| P2 | 节点 catalog / label 双维护 | 前后端节点元数据漂移 |
| P2 | graph schema fallback edge 导出不全 | Flow 图不可信 |
| P2 | SSE heartbeat helper 存在但未接入 | 长连接中断难诊断 |

---

## 3. 目标文件与职责映射

### 后端核心

- `backend/src/app/agents/kb_chat_agentic_state.py`  
  当前统一承载 KB Chat 全量 state 与 reducer；本轮需要拆分 public/internal/transient 边界。
- `backend/src/app/agents/kb_chat_agentic_graph.py`  
  主图编排、主路由、compile/cache/context 入口；本轮需要统一路由真值与 graph 级策略。
- `backend/src/app/services/kb_chat_service.py`  
  fresh state 构造、checkpoint 恢复、streaming、protocol envelope、graph schema 输出；本轮是 P0 修复主入口。
- `backend/src/app/core/checkpoint.py`  
  AsyncPostgresSaver 统一管理；需要配合恢复兼容、thread 行为验证。
- `backend/src/app/core/memory_store.py`  
  LangGraph Store 后端管理；需核对多用户命名空间与降级路径。
- `backend/src/app/agents/kb_chat_memory.py`  
  KB Chat 跨线程 memory namespace；需去掉 `local` 默认污染。

### 后端子图 / 节点契约

- `backend/src/app/agents/preprocess_subgraph.py`
- `backend/src/app/agents/retrieval_subgraph.py`
- `backend/src/app/agents/evidence_gate_subgraph.py`
- `backend/src/app/agents/kb_chat_agentic/preprocess.py`
- `backend/src/app/agents/kb_chat_agentic/reflection.py`
- `backend/src/app/agents/answer_subgraph.py` 或 `backend/src/app/agents/kb_chat_agentic/answer_subgraph.py`
- `backend/src/app/agents/kb_chat_agentic/tool_loop.py`
- `backend/src/app/agents/kb_chat_trace_nodes.py`
- `backend/src/app/agents/kb_chat_contracts.py`

### 前端 trace / schema / SSE

- `frontend/src/views/KbChatPage.tsx`
- `frontend/src/services/chats.ts`
- `frontend/src/services/kbChatTraceStore.ts`
- `frontend/src/services/kbChatTraceNodes.ts`
- `frontend/src/services/kbChatFlowSelectors.ts`
- `frontend/src/services/kbNodeCatalog.ts`
- `frontend/src/services/kbNodeLabels.ts`
- `frontend/src/lib/sse.ts`

### 建议新增测试文件

- `backend/tests/services/test_kb_chat_service_state_restore.py`
- `backend/tests/services/test_kb_chat_service_stream_protocol.py`
- `backend/tests/services/test_kb_chat_graph_schema.py`
- `backend/tests/services/test_kb_chat_concurrency.py`
- `backend/tests/agents/test_kb_chat_state_contract.py`
- `backend/tests/agents/test_kb_chat_round_buffers.py`
- `backend/tests/agents/test_kb_chat_routing_contract.py`
- `backend/tests/agents/test_kb_chat_retry_cache.py`
- `backend/tests/agents/test_kb_chat_memory_namespace.py`
- `frontend/src/services/kbChatTraceStore.test.ts`
- `frontend/src/services/kbChatTraceNodes.test.ts`
- `frontend/src/services/kbNodeCatalog.test.ts`
- `frontend/src/services/kbChatFlowSelectors.test.ts`
- `frontend/src/lib/sse.test.ts`

---

## 4. 执行顺序总览

1. **Chunk 1：checkpoint 恢复安全 + 同线程互斥 + user namespace 修正**
2. **Chunk 2：current-round reducer/buffer 重构**
3. **Chunk 3：State 契约瘦身与 input/output/internal 分层**
4. **Chunk 4：路由契约统一，去掉多真值**
5. **Chunk 5：retry/cache 真正落地**
6. **Chunk 6：observability/protocol/SSE 硬化**
7. **Chunk 7：前端 trace 与 graph schema 单一事实源**
8. **Chunk 8：回归验证、灰度发布、回滚预案**

原则：**任何 Chunk 未通过对应验证，不进入下一个 Chunk。**

---

## Chunk 1：checkpoint 恢复安全、同线程互斥、multi-user namespace 修正

**Why:** 这是最先要堵住的 correctness 问题。当前 fresh turn state 会被 checkpoint 整体覆盖；同 thread 并发又缺保护；`user_id="local"` 会把跨线程 memory 错写到同一 namespace。三者叠加会直接造成生产事故。

**Depends on:** 无。

**Files:**

- Modify: `backend/src/app/services/kb_chat_service.py`
- Modify: `backend/src/app/core/checkpoint.py`
- Modify: `backend/src/app/agents/kb_chat_memory.py`
- Modify: `backend/src/app/core/memory_store.py`
- Modify: `backend/src/app/api/v1/endpoints/checkpoints.py`
- Modify: `backend/src/app/schemas/checkpoints.py`
- Create: `backend/tests/services/test_kb_chat_service_state_restore.py`
- Create: `backend/tests/services/test_kb_chat_concurrency.py`
- Create: `backend/tests/agents/test_kb_chat_memory_namespace.py`

### 任务清单

- [x] 定义 **checkpoint restore allowlist**：仅允许真正需要跨轮次保留的字段恢复，禁止把 `user_input`、本轮 `messages`、`pending_tool_calls`、`reflection`、`preprocess_next`、本轮 scratch 字段、run-local metrics 原样带入新轮次。
- [x] 将 `_sanitize_checkpoint_state(...)` 从“弱清洗”改为“schema-aware restore”：
  - 区分可恢复字段、需要 reset 的字段、需要迁移的 legacy 字段；
  - 对 reducer 字段使用专用恢复逻辑，不允许“整包覆盖”。
- [x] 把 `_prepare_kb_chat_execution(...)` 中 `state = {**state, **checkpoint_values}` 改成明确 merge pipeline：
  1. fresh input state；
  2. restore persisted safe fields；
  3. force authoritative run-scoped fields；
  4. reset transient scratch；
  5. 记录 restore audit/meta。
- [x] 明确 `messages` 恢复策略：只恢复 thread 级历史消息，不恢复旧轮次尚未完成的中间 AIMessage/tool call 残留；若发现 checkpoint 与数据库历史冲突，优先使用定义好的 authoritative source，并记告警。
- [x] 参照 general chat 的 `_ensure_no_running_general_run(...)`，为 KB Chat 增加 `_ensure_no_running_kb_chat_run(...)`：
  - session 行锁；
  - 查 RUNNING run；
  - 冲突时返回 409；
  - resume/clarification 分支也纳入 single-flight。
- [x] 去掉 `memory_keys.user_id="local"` 与 `append_kb_chat_memory_entry(... user_id="local")` 的硬编码：
  - 从认证上下文/会话所有者/运行时 context 中获取真实 user id；
  - 如果缺失，定义显式降级策略（如匿名 user namespace），但禁止使用共享常量值。
- [x] 调整 `kb_chat_user_namespace(...)` 默认值策略，禁止无差别回退到 `local`；若必须降级，应以 session/thread 维度隔离。
- [x] 为 checkpoint/restore 增加最小 audit 字段：
  - `checkpoint_restore_applied`
  - `checkpoint_restore_source_checkpoint_id`
  - `checkpoint_restore_reset_fields`
  - `checkpoint_restore_legacy_fields`
- [x] 检查 checkpoint endpoint/schema 输出，避免旧状态直出导致前端/排障继续误读。

### 验收标准

- [x] 新一轮提问时，不再从旧 checkpoint 恢复本轮 `user_input/reflection/preprocess_next/pending_tool_calls`。
- [x] 同一 session/thread 并发发起两个 KB Chat run 时，第二个请求稳定返回冲突错误，不出现 checkpoint 竞争写。
- [x] memory/store namespace 不再出现共享 `local` user id。
- [x] clarifying resume 不破坏 single-flight 规则。

### 验证命令

- [x] `cd backend; uv run pytest tests/services/test_kb_chat_service_state_restore.py -q`
- [x] `cd backend; uv run pytest tests/services/test_kb_chat_concurrency.py -q`
- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_memory_namespace.py -q`
- [x] `cd backend; uv run ruff check .`

### 提交建议

- [ ] `git commit -m "fix(kb-chat): harden checkpoint restore and thread isolation"`

### Do Not Do

- [ ] 不在本 Chunk 顺手重构整个 State。
- [ ] 不在尚未明确 authoritative source 之前混合 DB history、checkpoint messages、前端 staged message。

---

## Chunk 2：current-round reducer / buffer 重构

**Why:** `subquery_runs` 和 `answer_review_runs` 当前是 reducer 累加字段，却被当作“当前轮缓冲区”使用，这是 LangGraph 语义层面的错误。必须先把“当前轮 scratch”与“跨轮历史”分开。

**Depends on:** Chunk 1。

**Files:**

- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/src/app/agents/evidence_gate_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
- Modify: `backend/src/app/agents/answer_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Create: `backend/tests/agents/test_kb_chat_round_buffers.py`
- Create: `backend/tests/agents/test_kb_chat_state_contract.py`

> **Implementation note (2026-03-13):** 本 Chunk 采用低风险方案：保留 reducer history 字段，给 `subquery_runs` / `answer_review_runs` 增加 `retrieval_round` / `review_round` 归属，并让 merge / trace / display 只消费当前轮数据；更彻底的字段拆分与私有 state 下放留到 Chunk 3。

### 任务清单

- [x] 盘点所有 reducer 字段，按语义分三类：
  1. append-only history；
  2. per-superstep fan-out merge；
  3. current-round scratch（必须移出 reducer）。
- [x] 重构 `subquery_runs`：
  - 本 Chunk 保留 append-only reducer history，不再尝试用 `[]` 清空；
  - 为每个 run 标记 `retrieval_round`，并在 merge / graph display 中只消费 active round。
- [x] 重构 `answer_review_runs`：
  - 本 Chunk 保留 append-only reducer history，不再把它当作 resettable current-round buffer；
  - 为每个 review run 标记 `review_round`，并在 fuse / trace 中只消费 active round。
- [x] 所有“清空 reducer 字段”的逻辑一律替换为：
  - round_id 增长；
  - 切换新容器 key；
  - 或非 reducer override 字段 reset。
- [x] 给 `transform_query_for_retry(...)`、`complexity_classify(...)`、answer repair/review 重试路径补显式 round 过滤与当前轮隔离，确保：
  - 上一轮 subquery/review artifact 不污染下一轮；
  - stage summary 只保留需要跨轮分析的聚合结果。
- [x] 更新 `kb_chat_trace_nodes.py`：node_io 展示不能继续默认读取“累加后全量 runs”作为当前轮细节。
- [x] 为 round-local 结果加入显式 `round_id` / `doc_gate_round` / `review_round` 归属，避免 trace 与调试误解。

### 验收标准

- [x] 连续两轮 retrieval retry 后，当前轮 fused evidence 仅包含当前 round 的 branch 结果。
- [x] answer review retry 不再带出旧轮 citation/factual/answerability judge 结果。
- [x] reducer 字段只用于 append/merge 语义，不再承担 resettable scratch buffer。

### 验证命令

- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_round_buffers.py -q`
- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py -q`
- [x] `cd backend; uv run ruff check .`

### 提交建议

- [ ] `git commit -m "fix(kb-chat): separate round-local buffers from reducer history"`

### Do Not Do

- [ ] 不用“每次写空列表前先删 key”这类补丁规避 reducer 语义。
- [ ] 不把所有历史直接丢弃；保留必要 round history 以支持调试与审计。

---

## Chunk 3：State 契约瘦身与 input/output/internal 分层

**Why:** 当前 `KbChatAgenticState` 既是输入、又是输出、又是 scratch pad、又是 checkpoint payload，字段过多且重复。必须按最新 LangGraph 模式把输入/输出/内部状态边界收紧，否则后续任何修复都会继续失控。

**Depends on:** Chunk 1-2。

**Files:**

- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/src/app/agents/evidence_gate_subgraph.py`
- Modify: `backend/src/app/agents/answer_subgraph.py`
- Modify: `backend/src/app/services/kb_chat_service.py`
- Create: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `docs/知识库问答全流程-现状分析.md`

> **Progress note (2026-03-13 / round 1):** 已完成第一轮最小收敛：新增 `KbChatInputState` / `KbChatOutputState` typed contract，删除 `display_context` 与 `compressed_context` 两组重复持久化字段，`make_run_context(...)` 现支持显式 authoritative `user_id` / `kb_ids` / `runtime_config` 注入，并新增 `backend/tests/agents/test_kb_chat_state_schema.py` 覆盖该批变更。完整的 context migration、state/output 进一步收紧和文档重写继续留在本 Chunk 后续步骤。
>
> **Progress note (2026-03-13 / round 2):** 已补齐 runtime-context 读取链闭环：`runtime_config.py`、`preprocess.py`、`reflection.py` 现优先从 `Runtime.context` 解析 `runtime_config` / `thread_id` / `user_id` / `kb_ids`；`dispatch_fuse.make_send_task(...)` 删除 fanout branch 对 `memory_keys` / `runtime_config` 的冗余透传，仅保留 branch 真正需要的 `loop_counts` / `retrieval_budget`；`_retrieval_budget_plan(...)` 不再把动态预算回写到 `state["runtime_config"]`。新增红灯 `backend/tests/agents/test_kb_chat_runtime_context.py` 已转绿，并完成相关回归。
>
> **Progress note (2026-03-13 / round 3):** 主图 `KbChatAgenticGraph` 已显式绑定 `input_schema=KbChatInputState` / `output_schema=KbChatOutputState`，并新增 `test_kb_chat_graph_uses_public_input_output_schema` 回归测试，确保 graph 对外输入/输出边界不再退化回全量内部 state。`KbChatInternalState` 显式命名、私有节点 schema 下放和旧 checkpoint version 收口仍留在本 Chunk 后续步骤。
>
> **Progress note (2026-03-13 / round 4):** `make_initial_state(...)` 与 service fresh invoke 路径已停止把 `memory_keys` / `runtime_config` 注入可持久化 state，运行时不变量统一通过 `run_context` 注入；同时显式引入 `KbChatInternalState` 并切换主图/子图 `state_schema`，`schema_version` 现会随 fresh state 持久化，checkpoint summary 的 `schema_version` 类型也已与 `STATE_SCHEMA_V3` 对齐。旧 helper 对 state fallback 仍保留，仅用于 legacy/单测兼容，不再作为 fresh invoke 真值来源。
>
> **Progress note (2026-03-13 / round 5):** 已补齐 checkpoint schema 边界：`_CheckpointRestorePlan` / restore audit 新增 `checkpoint_restore_schema_supported`，resume 路径仅在 `schema_version == STATE_SCHEMA_V3` 时恢复 checkpoint messages；对未知 schema 显式拒绝恢复并回退到 fresh turn 重建路径。新增回归测试覆盖“支持版本恢复 / 未知版本拒绝恢复”两条分支。
>
> **Progress note (2026-03-13 / round 6):** 已完成重复字段第二轮收敛：`KbChatInternalState` / `make_initial_state(...)` 不再包含 `doc_gate_state` / `doc_gate_scores` / `answer_quality`；`_doc_gate_fuse(...)` / `_doc_gate_route(...)`、`_answer_commit(...)`、`confidence_calibrate(...)`、`kb_chat_trace_nodes.py` 与 `KbChatService._build_node_io_summary(...)` 已统一切到 `stage_summaries["doc_gate_fuse"]`、`stage_summaries["doc_gate_route"]` 与 `stage_summaries["answer_subgraph"]`。新增针对 `confidence_calibrate`、evidence gate trace 与 answer_subgraph io summary 的红灯测试已转绿，当前回归为 `26 passed` + `ruff check .` 通过。

### 任务清单

- [x] 设计三层 schema：
  - `KbChatInputState`：本轮输入最小集（如 `messages`, `user_input`）；
  - `KbChatOutputState`：最终对外输出最小集（如 `final_answer`, `confidence_*`, `clarification_payload`, `stage_summaries` 中的必要公开部分）；
  - `KbChatInternalState`：内部共享字段；
  - 必要时增加私有节点输入/输出 schema，而不是继续堆在全局 state。
- [x] 主图 `StateGraph(...)` 已绑定 public `input_schema` / `output_schema`，新增回归测试覆盖 graph builder 的输入/输出边界。
- [x] 补齐 runtime-context 读取链：`reflection.py` / `preprocess.py` / `runtime_config.py` 的动态配置与 memory scope 优先读取 `Runtime.context`，fanout branch 不再透传 `memory_keys` / `runtime_config`，`_retrieval_budget_plan(...)` 不再回写 `state["runtime_config"]`。
- [x] 将 `runtime_config`、`thread_id`、`user_id`、`kb_ids` 从“可持久化 mutable state”迁出到 `context_schema` / `Runtime.context`，并统一由 graph `make_run_context(...)` 注入。
- [ ] 收敛重复字段：
  - [x] `display_context` vs `merged_context`：只保留一个 canonical 文本，另一个改为 trace-only 派生值或删除；
  - [x] `compressed_context` vs `final_context`：明确“压缩产物”和“答案最终上下文”的层次，命名统一；
  - [x] `doc_gate_state` / `doc_gate_scores` / `answer_quality`：删除重复持久化字段，消费方统一改读 `stage_summaries` / `reflection`；
  - [ ] `stage_summaries` 只保留可审计摘要，不再充当真实状态来源。
- [ ] 更新 `make_initial_state(...)` 和所有节点签名，使节点只读取它真正需要的 schema。
- [x] 新增/升级 `STATE_SCHEMA_V*` 版本策略，保证旧 checkpoint 能被迁移或显式拒绝。
- [ ] 文档同步：用新的 state contract 重写 KB Chat 主链路文档中的字段流转图。

### 验收标准

- [ ] graph invoke 输入不再需要携带一大包内部字段。
- [ ] graph 输出不再泄露大批 scratch 字段。
- [x] `runtime_config`/`user_id`/`thread_id` 不再在 state 和 context 两边重复维护。
- [x] 新旧 checkpoint 行为有明确版本边界和迁移/拒绝策略。

### 验证命令

- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py -q`
- [x] `cd backend; uv run pytest tests/services/test_kb_chat_service_state_restore.py -q`
- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py -q`
- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_runtime_context.py tests/agents/test_kb_chat_round_buffers.py tests/agents/test_kb_chat_state_contract.py tests/services/test_kb_chat_service_state_restore.py -q`
- [x] `cd backend; uv run ruff check .`

### 提交建议

- [ ] `git commit -m "refactor(kb-chat): split input output and internal graph state"`

### Do Not Do

- [ ] 不做“只改字段名不改语义”的假重构。
- [ ] 不把所有细节都塞回 `stage_summaries` 继续作为旁路状态仓库。

---

## Chunk 4：路由契约统一，消除多真值

**Why:** 当前路由既由 `Command(goto)` 驱动，又被 `preprocess_next`、`reflection.action`、`stage_summaries.*.goto/decision` 间接表达。继续保留多真值，后续排障和 trace 一定继续分叉。

**Depends on:** Chunk 3。

> **Progress note (2026-03-13 / round 1):** 已完成后端第一轮 routing contract 收敛：新增 `routing_decisions` 作为 canonical routing record，`prepare_messages(...)` / `ambiguity_check(...)`、`_doc_gate_route(...)`、`_answer_commit(...)` 现会写入结构化 `next_node / reason / reason_code / decision_source / retry_budget_snapshot / round_id`；`_route_after_preprocess_subgraph(...)`、`route_after_doc_grader(...)`、`route_after_answer_review(...)` 已优先读取 `routing_decisions`，`stage_summaries` 只保留审计摘要。新增 `backend/tests/agents/test_kb_chat_routing_contract.py`，当前后端回归为 `32 passed` + `ruff check .` 通过。前端 trace/schema 消费和 legacy fallback 的彻底删除仍留在本 Chunk 后续步骤。
>
> **Progress note (2026-03-13 / round 2):** 已在 worktree 内补齐前端本地依赖（`cd frontend; npm ci`），并验证现有前端 trace/schema 消费未被新 routing contract 破坏：`npm run test:unit -- kbChatFlowSelectors.test.ts kbChatTraceNodes.test.ts` 当前为 `12 files / 40 tests passed`，`npm run typecheck` 通过。当前前端未额外改代码，说明后端输出键位兼容现有前端消费；是否进一步把前端 selector 显式改为 `routing_decisions` 直读，留在后续收敛步骤。
>
> **Progress note (2026-03-13 / round 3):** 已完成 legacy routing fallback 删除：`prepare_messages(...)` / `make_initial_state(...)` / `preprocess_subgraph` 不再写入或透传 `preprocess_next`；`_route_after_preprocess_subgraph(...)`、`_route_after_ambiguity(...)`、`route_after_doc_grader(...)`、`route_after_answer_review(...)` 已删除对 `preprocess_next`、`reflection.action`、`reflection.review_passed`、`reflection.relevance_passed`、`clarification_payload` 的 routing fallback。`kb_chat_trace_nodes.py` 与 `KbChatService` 的 route consistency 统计也已去掉 `action -> goto` 兼容推断。当前验证：后端 `36 passed`、前端 `12 files / 40 tests passed`、`ruff check .` 通过。

**Files:**

- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
- Modify: `backend/src/app/agents/evidence_gate_subgraph.py`
- Modify: `backend/src/app/agents/answer_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `frontend/src/services/kbChatFlowSelectors.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.ts`
- Create: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `frontend/src/services/kbChatFlowSelectors.test.ts`

### 任务清单

- [x] 定义统一规则：**真正驱动图跳转的唯一真值是 `Command(goto=...)` 或 graph conditional function 的返回值**。
- [x] `preprocess_next` 已从 fresh state / prepare_messages / preprocess_subgraph 写路径移除；仅在 checkpoint reset allowlist 中保留 legacy 清洗语义。
- [x] `reflection.action` 只保留为“用户可见/审计可读”的动作摘要，graph router 不再依赖它。
- [x] doc gate / answer review / finalize 路由统一输出结构化 routing record，例如：
  - `next_node`
  - `reason_code`
  - `decision_source`
  - `retry_budget_snapshot`
  - `round_id`
- [x] `_route_after_preprocess_subgraph(...)`、`_route_after_ambiguity(...)`、`route_after_doc_grader(...)`、`route_after_answer_review(...)` 改成读取统一 routing record，而不是散读 `reflection`、`preprocess_next`、clarification payload。
- [x] `stage_summaries` 中保留 `decision` / `reason` 仅作为只读摘要，不再反向驱动 graph。
- [ ] trace 展示改为：
  - 用 routing record 解释“为什么去下一个节点”；
  - 不再把多个来源拼接成一个模糊的“后续动作”。

### 验收标准

- [ ] 任一节点的下一跳都能从单一 routing record 追溯。
- [x] 删除/禁用 `preprocess_next` 后主链路仍然可运行。
- [ ] trace 中的“后续动作”与实际 graph 下一跳完全一致。

### 验证命令

- [x] `cd backend; uv run pytest tests/agents/test_kb_chat_routing_contract.py -q`
- [x] `cd frontend; npm run test:unit -- kbChatFlowSelectors.test.ts kbChatTraceNodes.test.ts`
- [x] `cd backend; uv run ruff check .`
- [x] `cd frontend; npm run typecheck`

### 提交建议

- [ ] `git commit -m "refactor(kb-chat): unify graph routing contract"`

### Do Not Do

- [ ] 不在 graph router 中继续读取 2 个以上的路由字段。
- [ ] 不把 trace convenience 字段重新升级成控制流真值。

---

## Chunk 5：retry / cache 能力真正落地

**Why:** 现在图里有 `InMemoryCache` 却未启用，retry 也未系统配置。结果是代码里看起来“支持重试/缓存”，实际上生产链路并没有稳定收益。

**Depends on:** Chunk 3-4。

**Files:**

- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/src/app/agents/evidence_gate_subgraph.py`
- Modify: `backend/src/app/agents/answer_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
- Modify: `docs/langgraph_constraints.md`
- Create: `backend/tests/agents/test_kb_chat_retry_cache.py`

### 任务清单

- [ ] 盘点每个节点的 side effect 类型：
  - 纯函数节点；
  - LLM 节点；
  - 检索/数据库/外部 IO 节点；
  - 不允许自动重试的节点。
- [ ] 给可重试节点显式挂 `RetryPolicy`，至少覆盖：
  - retrieval/tool 调用；
  - doc gate grader；
  - answer review grader；
  - query transform；
  - 可能的模型 fallback 节点。
- [ ] 为不可重试节点写注释/元数据说明，避免默认重试误伤。
- [ ] 对 `_KB_CHAT_GRAPH_CACHE` 做二选一：
  1. 真正启用并设计 cache key / cache invalidation / hit metric；
  2. 删除死代码和误导性 compile 参数。
- [ ] 若启用 cache，明确只缓存纯输入确定、无隐私泄露风险、无副作用的节点输出。
- [ ] 记录 retry/cache 可观测指标：
  - `retry_attempts_total`
  - `retry_node_breakdown`
  - `graph_cache_hit_total`
  - `graph_cache_miss_total`
  - `cache_disabled_reason`
- [ ] 文档同步：明确哪些节点启用 retry，哪些字段进入 cache key，哪些不缓存。

### 验收标准

- [ ] graph 中不存在“看起来有 cache，实际恒为 None”的悬空能力。
- [ ] 关键外部调用节点具备可解释的 retry 策略。
- [ ] retry/cache hit 能被 metrics、trace 或日志验证。

### 验证命令

- [ ] `cd backend; uv run pytest tests/agents/test_kb_chat_retry_cache.py -q`
- [ ] `cd backend; uv run ruff check .`

### 提交建议

- [ ] `git commit -m "feat(kb-chat): activate retry and rationalize graph cache"`

### Do Not Do

- [ ] 不要给有副作用的节点盲加 retry。
- [ ] 不要缓存带用户敏感内容且无 redaction 的大对象。

---

## Chunk 6：observability / protocol / SSE 硬化

**Why:** 现在 `node_io` 直接发完整 snapshot，前后端协议漂移降级能力弱，heartbeat 也没接上，生产环境很难长期稳定观测。

**Depends on:** Chunk 1-5。

**Files:**

- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `backend/src/app/agents/kb_chat_contracts.py`
- Modify: `backend/src/app/services/kb_chat_service.py`
- Modify: `backend/src/app/api/sse.py`
- Modify: `frontend/src/views/KbChatPage.tsx`
- Modify: `frontend/src/services/chats.ts`
- Modify: `frontend/src/services/kbChatTraceStore.ts`
- Modify: `frontend/src/lib/sse.ts`
- Create: `backend/tests/services/test_kb_chat_service_stream_protocol.py`
- Create: `frontend/src/lib/sse.test.ts`
- Modify: `frontend/src/services/kbChatTraceStore.test.ts`

### 任务清单

- [ ] `node_io` 改为 **summary-first, snapshot-optional**：
  - 默认仅发 `input_summary` / `output_summary` / `display_*_items`；
  - 完整 snapshot 仅在 debug 开关下启用；
  - 加 payload size cap、字段 allowlist、PII redaction。
- [ ] 为 `kb_chat_trace_nodes.py` 增加统一 snapshot 裁剪策略：
  - 最大字符数；
  - 最大数组长度；
  - 大文本改为 preview + size；
  - 敏感字段清洗。
- [ ] `validate_event_envelope_v2(...)` 增加“严格校验 + 宽松降级”双路径：
  - 后端统计 drift；
  - 前端尽可能 salvage 可识别字段；
  - 对未知/缺失字段保留 warning，不直接失明。
- [ ] 明确 `custom` 事件 taxonomy：
  - `node_io`
  - `review_signal`
  - `guardrail_warning`
  - `heartbeat`（如采用 event 形式）
  - 其他未消费类型必须登记。
- [ ] 把 `format_sse_comment(...)` 真的接入流式输出，或定义显式 heartbeat event；目标是在长时间无 token/无 update 时也保持连接活跃。
- [ ] 前端 `parseSseStream(...)` / stream loop 增加 heartbeat 容忍与 idle 监测，不把 comment/heartbeat 当异常。
- [ ] 为 protocol 记录更多指标：
  - `protocol_required_field_drift_count`
  - `protocol_salvage_count`
  - `node_io_snapshot_truncated_count`
  - `custom_event_unhandled_count`
  - `sse_heartbeat_sent_count`
  - `sse_heartbeat_gap_ms_p95`

### 验收标准

- [ ] 常规生产流量下 `node_io` 不再携带完整大对象 snapshot。
- [ ] 协议字段轻微漂移时，前端 trace 仍能保留核心节点时间线并给 warning。
- [ ] 长时间检索/评审阶段 SSE 不再因无数据而疑似“卡死”。

### 验证命令

- [ ] `cd backend; uv run pytest tests/services/test_kb_chat_service_stream_protocol.py -q`
- [ ] `cd frontend; npm run vitest -- run src/services/kbChatTraceStore.test.ts src/lib/sse.test.ts`
- [ ] `cd frontend; npm run typecheck`
- [ ] `cd backend; uv run ruff check .`

### 提交建议

- [ ] `git commit -m "fix(kb-chat): harden stream protocol and node observability"`

### Do Not Do

- [ ] 不要因为“方便调试”继续在默认流里发全量 state。
- [ ] 不要让 heartbeat 与业务事件复用同一不透明 payload。

---

## Chunk 7：前端 trace 与 graph schema 单一事实源

**Why:** 后端已有 `KB_CHAT_NODE_METADATA` 和 graph schema 输出，前端仍维护 `KB_NODE_CATALOG` 静态映射；同时 `custom` 不消费、fallback edges 不完整，最终导致 trace 看起来“能显示”，但并不可信。

**Depends on:** Chunk 4、Chunk 6。

**Files:**

- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `backend/src/app/services/kb_chat_service.py`
- Modify: `backend/src/app/schemas/chats.py`
- Modify: `frontend/src/services/chats.ts`
- Modify: `frontend/src/services/kbNodeCatalog.ts`
- Modify: `frontend/src/services/kbNodeLabels.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.ts`
- Modify: `frontend/src/services/kbChatTraceStore.ts`
- Modify: `frontend/src/views/KbChatPage.tsx`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.test.ts`
- Modify: `frontend/src/services/kbNodeCatalog.test.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.test.ts`
- Create: `backend/tests/services/test_kb_chat_graph_schema.py`

### 任务清单

- [ ] 明确 **单一事实源**：
  - 节点 `label/phase/order` 以后端 graph schema / node metadata 为准；
  - 前端仅保留 stage UI 装饰信息（颜色、图标、stage 分组规则），不再手写业务节点 label/order。
- [ ] `get_graph_schema(...)` 输出补足：
  - 明确 version/hash；
  - 完整 node metadata；
  - 完整 edges（含 conditional edge、子图边、fallback builder 导出的 edge）。
- [ ] 修正 `_build_drawable_graph_from_builder(...)`：
  - 覆盖 nested builder / branch ends / conditional destination；
  - 增加 edge 去重与稳定排序；
  - 明确遗漏场景测试。
- [ ] 前端 trace 构建逻辑改为：
  - 优先消费服务端 schema；
  - 无 schema 时再降级到本地兜底；
  - observed node 仅作为“补洞”，不是主目录。
- [ ] 前端开始消费 `custom` 事件，至少支持 review / guardrail / heartbeat 中与 UI 相关的事件；若某类 `custom` 明确不展示，要在 reducer 中计数并记录原因。
- [ ] `resolveKbNodeLabel(...)`、`resolveKbNodeStageId(...)`、`buildTraceStageGroups(...)` 全部以服务端 schema 优先。
- [ ] FlowPanel 与 trace 节点显示继续满足“只展示中文节点名，不暴露英文内部 id”的现有产品约束。

### 验收标准

- [ ] 后端新增节点 metadata 后，前端无需手改 catalog 即可正确显示中文节点名、阶段和顺序。
- [ ] graph schema fallback 与正常导出在边集合上基本一致。
- [ ] `custom` 事件不再默默丢失。

### 验证命令

- [ ] `cd backend; uv run pytest tests/services/test_kb_chat_graph_schema.py -q`
- [ ] `cd frontend; npm run vitest -- run src/services/kbNodeCatalog.test.ts src/services/kbChatTraceNodes.test.ts src/services/kbChatTraceStore.test.ts src/components/chat/KbChatFlowPanel.test.ts`
- [ ] `cd frontend; npm run typecheck`
- [ ] `cd frontend; npm run build`

### 提交建议

- [ ] `git commit -m "refactor(kb-chat): make backend schema the trace source of truth"`

### Do Not Do

- [ ] 不要继续维护两套节点 label/order 真值。
- [ ] 不要用 observed node 反推 schema 作为长期方案。

---

## Chunk 8：回归验证、灰度发布与回滚预案

**Why:** 前 7 个 Chunk 涉及 State、路由、持久化、流式协议，是高风险主链路改造。必须独立设计灰度、回滚和验证，不允许“代码看起来对”就直接上线。

**Depends on:** Chunk 1-7 全部完成。

**Files:**

- Modify: `docs/知识库问答全流程-现状分析.md`
- Modify: `docs/langgraph_constraints.md`
- Create: `docs/runbooks/kb-chat-state-and-trace-hardening.md`
- Create: `docs/runbooks/kb-chat-gray-release-checklist.md`

### 任务清单

- [ ] 建立回归矩阵：
  - 新会话首问；
  - 多轮追问；
  - retrieval retry；
  - doc gate retry；
  - clarification interrupt/resume；
  - 同 session 并发冲突；
  - schema fallback；
  - frontend trace custom/heartbeat；
  - checkpoint 恢复后继续执行。
- [ ] 建立 live repro 脚本与人工验收步骤：
  - 启动后端/前端；
  - 新建 KB Chat session；
  - 连发问题触发 retrieval retry 与 clarification；
  - 检查 node_io、run_state、graph schema、checkpoint history。
- [ ] 建立灰度指标门禁：
  - route consistency
  - final state consistency
  - clarification consistency
  - protocol drift
  - p95 latency increase
  - thread conflict count
  - unhandled custom events
- [ ] 定义回滚点：
  - checkpoint restore 新逻辑可开关；
  - schema-driven frontend 可降级；
  - node_io snapshot debug-only 可一键关闭；
  - retry/cache 可按节点关闭。
- [ ] 发布后观察窗口内保留 anomaly sample，并固定留证目录。

### 验收标准

- [ ] 全量自动化测试通过。
- [ ] 关键 live repro 场景全部通过，并有日志/SSE 证据。
- [ ] 灰度指标无新增红线。

### 验证命令

- [ ] `cd backend; uv run pytest`
- [ ] `cd backend; uv run ruff check .`
- [ ] `cd frontend; npm run typecheck`
- [ ] `cd frontend; npm run build`
- [ ] `pwsh -ExecutionPolicy Bypass -File .\\scripts\\start_all.ps1`

### 提交建议

- [ ] `git commit -m "docs(kb-chat): add rollout and validation runbooks"`

### Do Not Do

- [ ] 不要跳过 live repro。
- [ ] 不要在没有 checkpoint 兼容策略前直接清库上线。

---

## 5. 跨 Chunk 通用验收要求

- [ ] 所有新增/修改的状态字段都要在 state contract 文档中登记：来源、消费者、是否持久化、是否 reducer、是否可公开。
- [ ] 所有 graph 路由节点都要有对应测试，至少覆盖 happy path、retry path、force_exit path。
- [ ] 所有 SSE event type 都要有“发送方 + 消费方 + 降级行为”三元说明。
- [ ] 所有跨线程 memory 命名空间都要能解释 `user_id`、`thread_id`、`kb_scope` 的来源。
- [ ] 所有 payload 裁剪策略都要有 size limit 常量、日志计数、测试。

---

## 6. 建议实施节奏

### Phase A（1-2 个 PR）

- Chunk 1
- Chunk 2

**目标：** 先把最危险的状态污染、并发覆盖、多用户 namespace 问题止血。

### Phase B（2-3 个 PR）

- Chunk 3
- Chunk 4

**目标：** 建立长期可维护的 State 与 routing contract。

### Phase C（2 个 PR）

- Chunk 5
- Chunk 6
- Chunk 7

**目标：** 把“看起来存在”的能力变成“真正可验证”的能力，并打通前后端 trace 闭环。

### Phase D（1 个 PR）

- Chunk 8

**目标：** 灰度、回滚、runbook、文档闭环。

---

## 7. 最终完成定义（Definition of Done）

全部满足后，才允许声称“KB Chat 图状态/持久化/可观测问题已修复”：

- [ ] 新旧 checkpoint 兼容策略明确，且不存在新轮次状态泄漏。
- [ ] 同一 thread 不会并发执行多个 KB Chat run。
- [ ] `user_id="local"` 从 KB Chat state/memory 主链路中彻底移除。
- [ ] reducer 字段只承载 append/merge 语义，不再承载 current-round reset 语义。
- [ ] graph routing 只有一个控制流真值，trace 展示与真实跳转一致。
- [ ] retry/cache 能力可被测试和 metrics 证明，而不是死代码。
- [ ] node_io 默认 payload 已裁剪，前端能处理 custom/heartbeat/field drift。
- [ ] backend schema 成为节点元数据单一事实源，frontend 不再双维护业务节点 label/order。
- [ ] 自动化测试、前端构建、live repro、灰度指标全部通过。
