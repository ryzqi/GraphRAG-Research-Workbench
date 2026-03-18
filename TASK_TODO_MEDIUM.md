# Task Todo - Medium

> 执行蓝图：KB Chat LLM 驱动查询理解与审查收口
> 范围限定：仅改 KB Chat；直接在 `master` 执行；不改 general chat；不重做 Milvus 检索引擎。

## Part 1: 边界与验收口径

### 1.1 固化本轮目标
- [ ] Task: 把已批准设计收敛成可执行目标与不做项
- Goal: 开工前消除范围漂移
- Done when: 目标、不做项、验证口径可直接据此执行
- Deliverables: 本文件、`TASK_TODO_FINE.md`
- Notes:
  - 删除 `evidence_gate_subgraph / doc_gate_*`
  - 删除 `confidence_calibrate`
  - `coref_rewrite -> resolve_reference`
  - `normalize_rewrite -> query_normalize`
  - `retrieval_budget_plan -> retrieval_plan`
  - `draft_generate` 去掉 `max_tokens=1024`
  - `answer_review_factual` 全量读取 `final_context` 与 `draft_answer`

### 1.2 固化不做项
- [ ] Task: 写清本轮明确不做的内容
- Goal: 防止顺手扩改
- Done when: 执行时可据此拒绝无关重构
- Deliverables: 不做项清单
- Notes:
  - 不重做 Milvus 检索主实现
  - 不改 general chat
  - 不重做前端页面交互范式
  - 不把多个理解节点合并成黑盒大节点

### 1.3 固化验证命令
- [ ] Task: 记录本轮必须执行的后端/前端验证命令
- Goal: 任何“已完成”表述都能对账到命令输出
- Done when: 命令与目标覆盖面明确
- Deliverables: 验证命令列表
- Notes:
  - `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/agents/test_kb_chat_runtime_context.py tests/agents/test_kb_chat_trace_nodes.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py -q`
  - `cd backend; uv run ruff check .`
  - `cd frontend; npm run typecheck`
  - `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatAnswerReveal.test.ts src/services/kbChatTraceNodes.test.ts`

## Part 2: 执行顺序

### 2.1 先锁 live contract
- [ ] Task: 先写失败测试，锁住删除节点、重命名节点、终态路由与前端 catalog
- Goal: 避免一边改一边漂
- Done when: 目标测试先红，且失败原因正确
- Deliverables: backend/frontend 合同失败用例

### 2.2 再做 backend runtime 收口
- [ ] Task: 依次完成 reference resolution、query normalize、retrieval plan、gate/finalize 删除、draft/review 改造
- Goal: 保持后端主链路每一段可独立验收
- Done when: 每一 slice 都有对应 GREEN 证据与独立 commit
- Deliverables: 后端实现补丁 + 定向通过测试

### 2.3 最后做 frontend/docs 对齐
- [ ] Task: 同步 node catalog、answer reveal、types/page state、docs
- Goal: 避免 backend 已删 contract 但 frontend/docs 仍引用旧节点
- Done when: targeted vitest/typecheck/doc 对齐完成
- Deliverables: 前端对齐补丁 + docs 更新

## Part 3: 风险与停点

### 3.1 模型节点 fail-open
- [ ] Task: 在实现时强制保留 `decision_source / fallback_used / fallback_reason`
- Goal: 避免“表面 LLM 驱动，失败时无痕降级”
- Done when: 新 LLM 节点都能从 stage summary 或 meta 看出回退痕迹

### 3.2 发现 blocker 即停
- [ ] Task: 若出现计划缺口、命令持续失败、contract 冲突无法收敛，则停止继续实现
- Goal: 不在 master 上盲改
- Done when: blocker 被如实上报，而不是猜测推进
