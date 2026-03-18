# Task Todo - Fine

> 执行蓝图：KB Chat LLM 驱动查询理解与审查收口
> 当前要求：先压缩上下文，直接在 `master` 执行；遵循最小改动、TDD、分片验证。

## Part 1: 规划与准备

### 1.1 固化执行边界
- [ ] Task: 将 approved spec 与 implementation plan 压缩成可执行边界
- Goal: 后续任何步骤都能回指到明确范围
- Inputs / Dependencies: `docs/superpowers/specs/2026-03-18-kb-chat-llm-driven-query-and-review-design.md`、`docs/superpowers/plans/2026-03-18-kb-chat-llm-driven-query-and-review-implementation.md`
- Procedure / Implementation notes: 明确 KB Chat only、master direct、fail-open、删除 evidence gate / confidence calibrate
- Output / Artifact: 本文件与 `TASK_TODO_MEDIUM.md`
- Done when: 不需要再口头解释范围即可开工
- Verification: 复核本文件是否覆盖目标/不做项/验证命令

### 1.2 校验仓库状态
- [ ] Task: 确认当前就在 `master` 且工作区干净
- Goal: 防止把脏工作区误带进主线
- Inputs / Dependencies: `git branch --show-current`、`git status --short`
- Procedure / Implementation notes: 已确认 `master` + clean；若状态变化需先记录
- Output / Artifact: 状态检查结果
- Done when: 可安全继续执行 Task 2
- Verification: 读取命令输出

## Part 2: 先写失败测试锁 contract

### 2.1 backend schema/state/routing 红灯
- [ ] Task: 在 backend tests 中先锁住删除项与重命名项
- Goal: 先证明 live contract 仍旧，再做实现
- Inputs / Dependencies: `backend/tests/agents/test_kb_chat_state_schema.py`、`test_kb_chat_state_contract.py`、`test_kb_chat_routing_contract.py`、`test_kb_chat_retry_cache.py`、`test_kb_chat_runtime_context.py`、`test_kb_chat_trace_nodes.py`、`backend/tests/services/test_kb_chat_graph_schema.py`、`test_kb_chat_service_semantic_cache.py`、`test_kb_chat_service_state_restore.py`
- Procedure / Implementation notes:
  - 断言旧节点被移除：`evidence_gate_subgraph`、`doc_gate_*`、`confidence_calibrate`
  - 断言新节点命名：`resolve_reference`、`query_normalize`、`retrieval_plan`
  - 断言不再公开 `confidence_score / confidence_level`
  - 断言 planner clamp/fallback 行为
- Output / Artifact: backend 失败测试
- Done when: 目标 pytest 在当前实现上稳定 FAIL，且 failure 原因正确
- Verification: 跑目标 pytest 看到 RED

### 2.2 frontend catalog/labels 红灯
- [ ] Task: 在 frontend tests 中锁住 renamed/removed nodes 与 answer reveal 终态语义
- Goal: 避免 backend 改完后 frontend 静默错位
- Inputs / Dependencies: `frontend/src/services/kbNodeCatalog.test.ts`、`kbNodeLabels.test.ts`、`kbChatAnswerReveal.test.ts`
- Procedure / Implementation notes:
  - 新增 `kbChatAnswerReveal.test.ts`
  - 断言 frontend catalog 不再出现删除节点
  - 断言 label fallback 只认新节点名
- Output / Artifact: frontend 失败测试
- Done when: vitest 在旧实现上 RED
- Verification: 跑 targeted vitest 看到 RED

### 2.3 提交红灯基线
- [ ] Task: 将失败测试作为单独 commit 落盘
- Goal: 保留 contract 锁定证据
- Inputs / Dependencies: 2.1 + 2.2 已完成
- Procedure / Implementation notes: 不混入运行时代码改动
- Output / Artifact: `test: lock KB Chat LLM-driven live contract`
- Done when: git commit 成功
- Verification: `git show --stat --oneline HEAD`

## Part 3: backend runtime 分片实现

### 3.1 `resolve_reference`
- [ ] Task: 用 LLM 驱动替换启发式 `coref_rewrite`
- Goal: 删除现有候选打分/替换逻辑，改为 fail-open 的引用解析
- Inputs / Dependencies: `backend/src/app/services/query_rewrite_service.py`、`backend/src/app/agents/kb_chat_agentic/preprocess.py`、`preprocess_subgraph.py`、`kb_chat_agentic_state.py`、新 prompt `backend/src/app/prompts/templates/kb_chat/resolve_reference.yaml`
- Procedure / Implementation notes:
  - 新 canonical 输出：`resolved_query`、`reference_resolution_meta`
  - node id 改成 `resolve_reference`
  - summary key 改成 `stage_summaries.resolve_reference`
  - 失败回原 query
- Output / Artifact: reference resolution slice
- Done when: focused pytest GREEN
- Verification: `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_trace_nodes.py -q -k "resolve_reference or preprocess"`

### 3.2 `query_normalize`
- [ ] Task: 将 `normalize_rewrite` 收口成规则优先再 LLM 的 `query_normalize`
- Goal: 保守规范化且不丢数字/时间/范围/否定/比较约束
- Inputs / Dependencies: `query_rewrite_service.py`、`preprocess.py`、`preprocess_subgraph.py`、`kb_chat_agentic_state.py`、`backend/src/app/prompts/templates/kb_chat/normalize_query.yaml`
- Procedure / Implementation notes:
  - node id 改成 `query_normalize`
  - summary key 改成 `stage_summaries.query_normalize`
  - 规则失败回原 query，LLM 失败回规则结果
- Output / Artifact: normalization slice
- Done when: focused pytest GREEN
- Verification: `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_routing_contract.py -q -k "query_normalize or normalize"`

### 3.3 `retrieval_plan`
- [ ] Task: 将 `retrieval_budget_plan` 改为 LLM 驱动的 `retrieval_plan`
- Goal: 保持 `retrieval_budget` 下游结构稳定，同时改为 LLM first + rule fallback
- Inputs / Dependencies: `backend/src/app/agents/retrieval_subgraph.py`、`kb_chat_agentic_state.py`、`kb_chat_trace_nodes.py`、新 prompt `backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml`
- Procedure / Implementation notes:
  - node id 改成 `retrieval_plan`
  - summary key 改成 `stage_summaries.retrieval_plan`
  - 数值统一 clamp
  - 非法输出回当前保守公式
- Output / Artifact: retrieval planning slice
- Done when: focused pytest GREEN
- Verification: `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py tests/services/test_kb_chat_graph_schema.py -q -k "retrieval_plan or budget"`

### 3.4 `context_compress`
- [ ] Task: 强化上下文压缩提示词与 fail-open 兜底
- Goal: 明确保留引文标签、数字、时间、例外、比较基线、因果前提
- Inputs / Dependencies: `backend/src/app/agents/retrieval_subgraph.py`、`backend/src/app/prompts/templates/kb_chat/context_compress.yaml`
- Procedure / Implementation notes:
  - 保留 `context_compress` node id
  - 新增“丢引文/变长/空输出”回退判定
  - summary 写清 fallback 痕迹
- Output / Artifact: compression slice
- Done when: focused pytest GREEN
- Verification: `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py -q -k "context_compress or compress"`

### 3.5 删除 evidence gate 与 confidence calibrate
- [ ] Task: 从 runtime graph、state、trace、service 中彻底删除 gate/finalize live contract
- Goal: 主链路收口为 `preprocess -> retrieval -> answer`
- Inputs / Dependencies: `backend/src/app/agents/kb_chat_agentic_graph.py`、`reflection.py`、`kb_chat_agentic_state.py`、`kb_chat_trace_nodes.py`、`kb_chat_trace_display_contract.py`、`backend/src/app/services/kb_chat_service.py`
- Procedure / Implementation notes:
  - 去掉 `build_evidence_gate_subgraph` / `route_after_doc_grader`
  - 删除 `confidence_calibrate`
  - 删除 `confidence_score / confidence_level / doc_gate_runs`
  - `answer_commit -> END`
  - `transform_query -> retrieval_subgraph`
  - `force_exit -> END`
- Output / Artifact: contract removal slice
- Done when: focused pytest GREEN
- Verification: `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py tests/agents/test_kb_chat_trace_nodes.py -q`

### 3.6 draft/review 收口
- [ ] Task: 删除草稿生成长度上限，并让 factual review 全量读取上下文与草稿
- Goal: 生成不再硬截断，事实审查不再切片输入
- Inputs / Dependencies: `backend/src/app/agents/kb_chat_agentic/reflection.py`、`backend/src/app/agents/kb_chat_agentic/answer_subgraph.py`
- Procedure / Implementation notes:
  - 去掉 `chat_model.bind(max_tokens=1024)`
  - 去掉 `final_context[:4000]`
  - 去掉 `draft[:2000]`
  - 保留 factual review LLM fail-open
- Output / Artifact: draft/review slice
- Done when: focused pytest GREEN
- Verification: `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py -q -k "draft_generate or answer_review_factual or factual"`

## Part 4: frontend 与 docs 对齐

### 4.1 frontend contract 对齐
- [ ] Task: 同步 node catalog / labels / answer reveal / service types / page state
- Goal: frontend 不再消费旧 gate/finalize 与 confidence 字段
- Inputs / Dependencies: `frontend/src/services/chats.ts`、`frontend/src/views/KbChatPage.tsx`、`frontend/src/services/kbNodeCatalog.ts`、`kbNodeLabels.ts`、`kbChatAnswerReveal.ts`、`kbChatTraceNodes.ts`
- Procedure / Implementation notes:
  - catalog 改为新节点名
  - 删除 removed node ids
  - 终态 reveal 不再依赖 `confidence_calibrate`
  - 删除/停用 `confidence_score / confidence_level` 读取
- Output / Artifact: frontend alignment slice
- Done when: targeted vitest/typecheck GREEN
- Verification:
  - `cd frontend; npm run typecheck`
  - `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatAnswerReveal.test.ts src/services/kbChatTraceNodes.test.ts`

### 4.2 docs 对齐
- [ ] Task: 更新运行路径与节点说明文档
- Goal: docs 不再误导后续实现与排障
- Inputs / Dependencies: `docs/流程图.md`、`docs/langgraph_constraints.md`
- Procedure / Implementation notes:
  - 替换旧节点名与旧 gate/finalize 路径
  - 写明新收敛链路与新 contract 边界
- Output / Artifact: docs patch
- Done when: 文档与当前 runtime graph 一致
- Verification: 目检 + grep 旧节点名是否仍残留于 live 描述

## Part 5: 全量验证与收尾

### 5.1 backend 验证
- [ ] Task: 跑目标 backend pytest 与 ruff
- Goal: 用 fresh evidence 证明主链路合同收口完成
- Inputs / Dependencies: Part 2-4 已完成
- Procedure / Implementation notes: 只在 targeted suite 全绿后才汇报“backend 完成”
- Output / Artifact: pytest + ruff 输出
- Done when: exit code 全部为 0
- Verification:
  - `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/agents/test_kb_chat_runtime_context.py tests/agents/test_kb_chat_trace_nodes.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py -q`
  - `cd backend; uv run ruff check .`

### 5.2 frontend 验证
- [ ] Task: 跑 typecheck 与 targeted vitest
- Goal: 用 fresh evidence 证明 frontend contract 已对齐
- Inputs / Dependencies: frontend slice 已完成
- Procedure / Implementation notes: answer reveal、新 node catalog、新 labels 都需覆盖
- Output / Artifact: typecheck + vitest 输出
- Done when: exit code 全部为 0
- Verification:
  - `cd frontend; npm run typecheck`
  - `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatAnswerReveal.test.ts src/services/kbChatTraceNodes.test.ts`

### 5.3 最终 diff/提交
- [ ] Task: 复核无关改动与旧节点残留后，按 slice/收尾提交
- Goal: 确保 master 上变更集可审计、可 grep
- Inputs / Dependencies: 所有验证已通过
- Procedure / Implementation notes:
  - 先 `git diff --stat`
  - 再 grep 旧 live node id 残留
  - 最后提交 docs/收尾
- Output / Artifact: final commits + handoff summary
- Done when: 能清楚汇报“哪些完成并验证，哪些未做”
- Verification: `git show --stat --oneline HEAD`
