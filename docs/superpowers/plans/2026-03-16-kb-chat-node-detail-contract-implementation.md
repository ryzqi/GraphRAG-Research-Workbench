# KB Chat Node Detail Contract Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 KB Chat 右侧节点详情收敛为“后端单一合同 + 前端纯渲染”模式，确保每个 live 节点稳定展示关键输入/关键输出，且不再回退原始 JSON/调试字段。

**Architecture:** 先用后端/前端定向测试锁住新的 display contract，再集中改 `backend/src/app/agents/kb_chat_trace_nodes.py`：补齐 canonical key、中文化、证据/判定/错误格式化与节点级输入输出白名单；随后删除前端 selector/panel 的二次筛选与 fallback 展示路径，让右侧面板只消费 `display_input_items` / `display_output_items`。最后以 node_io 协议测试、前端渲染测试、typecheck/ruff/pytest 形成闭环。

**Tech Stack:** Python 3.13, LangGraph, FastAPI, pytest, Ruff, React, TypeScript, Vitest, MUI

---

## File Structure Lock

### Production files

- Create: `backend/src/app/agents/kb_chat_trace_display_contract.py`
  - 承载纯展示合同 helper + authoritative per-node contract table：canonical key 映射、中文化、证据/判定/错误字符串格式化、节点输入输出白名单与顺序；保持 `kb_chat_trace_nodes.py` 只做 orchestration + wrapper 接线。
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
  - 唯一的后端节点详情接入点；负责调用 display-contract helper、挂接 wrapper、发出 start/end/error node_io 事件。
- Modify: `frontend/src/services/kbChatFlowSelectors.ts`
  - 从“按节点再筛一次字段 + 风险提示”收敛为“只消费后端合同 + 轻量归一”。
- Create: `frontend/src/components/chat/KbChatFlowNodeDetailSections.tsx`
  - 抽离右侧详情的“关键输入 / 关键输出 / 空态 / 列表渲染”子组件，避免继续膨胀 `KbChatFlowPanel.tsx`。
- Modify: `frontend/src/components/chat/KbChatFlowPanel.tsx`
  - 删除 snapshot/summary fallback 详情路径，仅编排 stage/node 展开态与子组件接线。

### Verification files

- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
  - 锁定节点 display item key、顺序、证据/判定/错误输出形态。
- Modify: `backend/tests/services/test_kb_chat_service_stream_protocol.py`
  - 锁定 emitted `node_io` 事件不会丢失 `display_input_items` / `display_output_items` / `error_summary`。
- Modify: `frontend/src/services/kbChatFlowSelectors.test.ts`
  - 锁定 selector 不再自造 risk hint / legacy compact policy。
- Modify: `frontend/src/components/chat/KbChatFlowPanel.test.ts`
  - 锁定无 JSON fallback、列表完整展示、失败态错误摘要、空态与状态映射。

### Read-only references

- Reference: `docs/superpowers/specs/2026-03-16-kb-chat-node-detail-contract-design.md`
- Reference: `frontend/src/services/chats.ts`
- Reference: `frontend/src/services/kbNodeCatalog.ts`
- Reference: `frontend/src/services/kbNodeLabels.ts`
- Reference: `frontend/src/services/kbChatEvidenceDisplay.ts`

---

## Chunk 1: Contract red tests

### Task 1: 锁定 backend display contract

**Files:**
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/services/test_kb_chat_service_stream_protocol.py`

- [ ] **Step 1: 先把 spec Section 5 转成“全量节点合同矩阵”失败测试**

必须逐个覆盖 spec Section 5 的全部 live 节点，并至少显式点名：
- `merge_context`
- `prepare_messages`
- `retrieval_budget_plan`
- `dispatch_subqueries`
- `retrieve_subquery`
- `answer_review_dispatch`
- `confidence_calibrate`
- `force_exit`

要求：
- 每个节点都断言输入 key、输出 key、顺序
- 例外节点（分发/规划/聚合/长文本/错误态）必须单独列出来，不允许只靠家族 heuristics

- [ ] **Step 2: 再补代表性家族测试，保证格式化语义正确**

覆盖至少四类节点：
- 判定节点：`complexity_classify` / `doc_gate_route`
- 证据节点：`retrieve` / `context_compress`
- 聚合节点：`doc_gate_fuse` / `answer_review_fuse`
- 长文本节点：`hyde` / `draft_generate` / `answer_repair` / `answer_commit`
- 失败节点：任选一个 error-phase 节点

预期锁定：
- 判定输出只有 `decision` / `reason` / `next_node_label`
- `next_node_label` 的解析顺序固定为 `KB_CHAT_NODE_METADATA.label -> graph schema metadata.label -> business fallback`
- `next_node_label` 走中文 label / 业务化兜底，不泄露内部 node id
- 证据输入/输出使用统一 `文档名 + chunk 内容` 字符串数组
- 长文本节点输出全文，且不降级为首条摘要
- `gate_results` / `review_results` 为逐项字符串数组
- `dispatch_targets` / `review_checks` 的 value 也必须是中文/业务化字符串，不允许保留内部 id
- error-phase 自带 `display_input_items` 与 `error_summary`

- [ ] **Step 3: 运行 backend 定向 pytest，确认现状失败**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/services/test_kb_chat_service_stream_protocol.py -q`

Expected:
- 失败点集中在旧 key（如 `complexity_level` / `score` / `route_targets` / `hyde_doc`）
- 或 emitted `node_io` 仍允许旧 fallback/旧排序

- [ ] **Step 4: 为 stream protocol 增加 node_io payload 保真测试**

验证点：
- `display_input_items` / `display_output_items` 不会在服务层 envelope 化时被剥离
- `error_summary` 在 error-phase 保留
- `node_path` / `node` 元数据继续存在，不影响新合同
- `next_node_label` 中文化结果在 node_io payload 中已完成
- `dispatch_targets` / `review_checks` 中文化结果在 node_io payload 中已完成

- [ ] **Step 5: 提交测试护栏**

Run: `git add backend/tests/agents/test_kb_chat_state_contract.py backend/tests/services/test_kb_chat_service_stream_protocol.py && git commit -m "test: lock KB Chat node detail contract"`

Expected: commit 成功，仅包含 backend 测试改动

### Task 2: 锁定 frontend 消费与渲染合同

**Files:**
- Modify: `frontend/src/services/kbChatFlowSelectors.test.ts`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.test.ts`

- [ ] **Step 1: 为 selector 写失败测试，禁止二次裁剪/风险提示**

新增断言：
- 已提供的 canonical item 不再被改名或替换
- `risk_hint` 不再自动追加
- `query_count` / `per_query_top_k` 等旧 key 被新 key 替代

- [ ] **Step 2: 为 panel 写失败测试，禁止 fallback JSON/details**

新增断言：
- 未提供 display items 时显示 `暂无关键输入` / `暂无关键输出`
- 不展示 `input_summary` / `output_summary` / `input_snapshot` / `output_snapshot`
- `idle` 状态显示 `待执行`
- 失败态显示 `错误信息`

- [ ] **Step 3: 运行 frontend 定向 vitest，确认现状失败**

Run: `cd frontend; npm run vitest -- run src/services/kbChatFlowSelectors.test.ts src/components/chat/KbChatFlowPanel.test.ts`

Expected:
- 失败点集中在旧 policy map、risk hint、fallback builder、旧状态映射

- [ ] **Step 4: 提交前端测试护栏**

Run: `git add frontend/src/services/kbChatFlowSelectors.test.ts frontend/src/components/chat/KbChatFlowPanel.test.ts && git commit -m "test: lock KB Chat detail panel contract"`

Expected: commit 成功，仅包含前端测试改动

---

## Chunk 2: Backend contract implementation

### Task 3: 提取统一格式化 helper，先解决“怎么表示”

**Files:**
- Create: `backend/src/app/agents/kb_chat_trace_display_contract.py`
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`

- [ ] **Step 1: 在新 helper 模块中定义纯展示格式化函数**

至少拆出：
- next-hop label resolver
- dispatch/review label resolver
- evidence/current_evidence formatter
- gate/review results formatter
- error summary formatter
- per-node input/output contract table

- [ ] **Step 2: 新增 next-hop / target / review 中文化 helper**

至少抽出：
- node id -> 中文 label
- review check id -> 中文 label
- dispatch target id -> 中文 label
- action/goto 业务化兜底文案
- 严格遵循 `KB_CHAT_NODE_METADATA.label -> graph schema metadata.label -> business fallback` 的 next-hop label 解析顺序

- [ ] **Step 3: 新增 evidence/current_evidence 格式化 helper**

要求：
- 统一输出 `string[]`
- 每项为 `文档名：...\nChunk 内容：...`
- 缺失标题时用 `未命名文档`
- 缺失正文时用 `正文缺失`
- 零证据时输出 `未检索到相关证据`

- [ ] **Step 4: 新增 gate_results / review_results 格式化 helper**

要求：
- 统一输出 `string[]`
- 每项为 `中文检查名：通过/未通过｜原因：...`
- 不透传 `citation` / `factual` / `doc_gate_sufficiency` 这类内部 id

- [ ] **Step 5: 新增 error-phase display helper**

要求：
- error-phase payload 也能得到完整 `display_input_items`
- `display_output_items` 至少包含 `error_summary`
- 默认错误文案为 `节点执行失败`

- [ ] **Step 6: 运行 backend 定向 pytest，确保 helper 级测试转绿**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py -q`

Expected: 新增 helper 相关断言通过；stream protocol 若仍失败留到 Task 5 收口

### Task 4: 重写 `_build_node_input_display_items`

**Files:**
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`

- [ ] **Step 1: 先按 spec 建立节点家族到输入 key 的映射**

直接落地“节点 -> 输入 key 顺序”全量表，不只按家族 heuristics，至少逐个列出：
- preprocess 例外节点
- retrieval 规划/分发/聚合节点
- review 分发/融合节点
- finalize 例外节点

- [ ] **Step 2: 用 canonical key 替换旧输入 key**

目标：
- `query` / `question` / `final_context` 等旧展示 key 不再直接出现在 UI 合同中
- 改成 `user_input` / `normalized_query` / `query_items` / `current_evidence` / `draft_answer` / `subquery` 等 spec key

- [ ] **Step 3: 处理列表/长文本/聚合输入**

确保：
- `recent_turns` 为字符串数组
- `current_evidence` 复用 evidence 格式化
- `gate_results` / `review_results` 为字符串数组
- `candidate_answer` / `draft_answer` 保持全文

- [ ] **Step 4: 删除仅为 UI fallback 服务的冗余输入字段**

不要再向右侧详情提供：
- 原始 query 别名
- 调试型计数/slot/signals
- 原始 snapshot JSON

- [ ] **Step 5: 运行 backend 定向 pytest**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py -q`

Expected: 输入 key/顺序断言通过

### Task 5: 重写 `_build_node_output_display_items`

**Files:**
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`

- [ ] **Step 1: 先按节点家族收敛输出 key**

直接落地“节点 -> 输出 key 顺序”全量表，至少显式列出：
- 判定节点：`decision` / `reason` / `next_node_label`
- 分发节点：`dispatch_targets`
- 规划节点：`planned_query_count` / `planned_per_query_top_k`
- 证据节点：`retrieved_evidence` / `compressed_evidence`
- 长文本节点：`hyde_docs` / `draft_answer` / `repaired_answer` / `final_answer`
- 例外节点：`merge_context`、`prepare_messages`、`answer_review_dispatch`、`force_exit`

- [ ] **Step 2: 处理判定节点的最小可读兜底**

当缺字段时：
- `reason` -> `未返回明确原因`
- `next_node_label` -> `结束` 或业务化默认值

- [ ] **Step 3: 处理特殊节点**

至少覆盖：
- `ambiguity_check` 追加 `clarification_prompt`
- `preprocess_exit` 可追加 `final_answer`
- `merge_subquery_context` / `context_compress` 输出聚合后的 canonical 证据列表
- `force_exit` 固定输出 `final_answer` / `reason` / `next_node_label=结束`
- `hyde` 输出 `hyde_docs`（不再退回首条 `hyde_doc`）

- [ ] **Step 4: 清掉旧 UI 冗余字段**

不要再输出：
- `score`
- `confidence_score`
- `confidence_level`
- `route_to`
- `route_targets`
- `best_answer`
- `risk_level`
- `query_strategy_signals`

除非这些值已被明确重编码到 spec 定义的业务文案里

- [ ] **Step 5: 运行 backend 定向 pytest + Ruff**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/services/test_kb_chat_service_stream_protocol.py -q && uv run ruff check .`

Expected: backend display contract 与基础静态检查通过

---

## Chunk 3: Frontend pure-render cleanup

### Task 6: 删除 selector 的二次策略层

**Files:**
- Modify: `frontend/src/services/kbChatFlowSelectors.ts`
- Modify: `frontend/src/services/kbChatFlowSelectors.test.ts`

- [ ] **Step 1: 删除 `NODE_DETAIL_POLICY_MAP` 与 `inferRiskHint`**

目标：
- selector 不再按节点另写一套 key 白名单
- selector 不再追加任何额外展示文案

- [ ] **Step 2: 保留最小归一逻辑**

仅保留：
- item 结构标准化
- 空数组安全处理

不要保留：
- 旧 compact policy
- 旧 dispatch/review 例外映射
- risk hint
- 任意形式的重排、去重、自动补字段

- [ ] **Step 3: 让测试改为验证“按后端合同原样消费”**

Run: `cd frontend; npm run vitest -- run src/services/kbChatFlowSelectors.test.ts`

Expected: selector 测试转绿，且不再依赖旧 policy map

- [ ] **Step 4: 提交 selector 收口**

Run: `git add frontend/src/services/kbChatFlowSelectors.ts frontend/src/services/kbChatFlowSelectors.test.ts && git commit -m "refactor: simplify KB Chat flow selectors"`

Expected: commit 成功，仅包含 selector 侧改动

### Task 7: 收口 FlowPanel 为纯渲染组件

**Files:**
- Create: `frontend/src/components/chat/KbChatFlowNodeDetailSections.tsx`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.tsx`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.test.ts`

- [ ] **Step 1: 移除默认详情构建对 `buildFallbackInputItems` / `buildFallbackOutputItems` 的依赖**

目标：
- 右侧详情默认只吃 `display_input_items` / `display_output_items`
- 无 display items 时直接进入空态，不再读 snapshot/summary 拼详情

- [ ] **Step 2: 固定渲染列表 / 长文本 / 错误态**

要求：
- `string[]` 逐项完整显示
- 长文本不截断摘要
- 失败态显示 `错误信息`
- 空态显示 `暂无关键输入` / `暂无关键输出`

- [ ] **Step 3: 补齐状态标签映射**

固定：
- `idle -> 待执行`
- `running -> 进行中`
- `completed -> 已完成`
- `failed -> 失败`
- `waiting_user -> 待补充`
- `skipped -> 已跳过`

- [ ] **Step 4: 抽离右侧详情子组件，减少 `KbChatFlowPanel.tsx` 体积**

要求：
- `KbChatFlowPanel.tsx` 只保留 stage/node 组织与展开控制
- `KbChatFlowNodeDetailSections.tsx` 负责关键输入/关键输出/空态列表渲染
- 测试仍从 `KbChatFlowPanel.test.ts` 入口覆盖

- [ ] **Step 5: 运行 panel 定向测试与 typecheck**

Run: `cd frontend; npm run vitest -- run src/components/chat/KbChatFlowPanel.test.ts && npm run typecheck`

Expected: panel 测试与 TS 类型检查通过

---

## Chunk 4: Cross-stack verification

### Task 8: 端到端验证 node_io → selector → panel 链路

**Files:**
- Modify: `backend/tests/services/test_kb_chat_service_stream_protocol.py`
- Modify: `frontend/src/services/kbChatFlowSelectors.test.ts`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.test.ts`

- [ ] **Step 1: 用一组代表性 payload 串起全链路断言**

至少验证：
- 判定节点 payload
- 证据节点 payload
- 分发节点 payload
- 长文本节点 payload
- 失败节点 payload

并显式断言：
- `未命名文档`
- `正文缺失`
- `未检索到相关证据`

- [ ] **Step 2: 运行跨端定向验证**

Run:
- `cd backend; uv run pytest tests/services/test_kb_chat_service_stream_protocol.py -q`
- `cd frontend; npm run vitest -- run src/services/kbChatFlowSelectors.test.ts src/components/chat/KbChatFlowPanel.test.ts`

Expected: 右侧详情关键字段不再被后端/前端任一层改写

- [ ] **Step 3: 记录未覆盖风险**

若当前回归只覆盖静态 display contract，需在提交说明中明确：
- 未做 live SSE 复放
- 未做浏览器人工验收
- 风险记录落在仓库根提交说明与最终交付说明中，不额外新建文档

### Task 9: 最终验证与收尾

**Files:**
- Create: `backend/src/app/agents/kb_chat_trace_display_contract.py`
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/services/test_kb_chat_service_stream_protocol.py`
- Modify: `frontend/src/services/kbChatFlowSelectors.ts`
- Modify: `frontend/src/services/kbChatFlowSelectors.test.ts`
- Create: `frontend/src/components/chat/KbChatFlowNodeDetailSections.tsx`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.tsx`
- Modify: `frontend/src/components/chat/KbChatFlowPanel.test.ts`

- [ ] **Step 1: 跑 backend 最终验证**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/services/test_kb_chat_service_stream_protocol.py -q && uv run ruff check .`

Expected: 全绿

- [ ] **Step 2: 跑 frontend 最终验证**

Run: `cd frontend; npm run vitest -- run src/services/kbChatFlowSelectors.test.ts src/components/chat/KbChatFlowPanel.test.ts && npm run typecheck && npm run build`

Expected: 全绿

- [ ] **Step 3: 提交实现**

Run: `git add backend/src/app/agents/kb_chat_trace_display_contract.py backend/src/app/agents/kb_chat_trace_nodes.py backend/tests/agents/test_kb_chat_state_contract.py backend/tests/services/test_kb_chat_service_stream_protocol.py frontend/src/services/kbChatFlowSelectors.ts frontend/src/services/kbChatFlowSelectors.test.ts frontend/src/components/chat/KbChatFlowNodeDetailSections.tsx frontend/src/components/chat/KbChatFlowPanel.tsx frontend/src/components/chat/KbChatFlowPanel.test.ts && git commit -m "feat: tighten KB Chat node detail contract"`

Expected: commit 成功，仅包含本特性的实现与测试

---

## 验证矩阵

- [ ] `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/services/test_kb_chat_service_stream_protocol.py -q`
- [ ] `cd backend; uv run ruff check .`
- [ ] `cd frontend; npm run vitest -- run src/services/kbChatFlowSelectors.test.ts src/components/chat/KbChatFlowPanel.test.ts`
- [ ] `cd frontend; npm run typecheck`
- [ ] `cd frontend; npm run build`

## 当前执行策略

- 先执行 **Chunk 1 + Chunk 2**：先锁合同，再集中改后端单一真值源。
- 只有 backend 合同稳定后，才进入 **Chunk 3** 删除前端 fallback/policy。
- **Chunk 4** 只做验证与收尾，不在这一轮额外扩 scope 到 trace stage、catalog、graph schema 或 docs。
