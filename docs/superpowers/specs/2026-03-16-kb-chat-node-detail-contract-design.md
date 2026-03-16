# KB Chat 节点关键输入/输出展示合同设计

> 状态：2026-03-16 已完成设计澄清，等待 spec review 与用户最终审阅。

## 1. 背景

当前知识库问答右侧的节点执行过程已经具备节点级 trace 能力，但“关键输入 / 关键输出”仍存在以下问题：

- 部分节点已做定制，部分节点仍依赖通用 fallback；
- 同一类节点的信息密度不一致，用户看到的内容有时偏调试、偏原始；
- 前后端同时维护筛选逻辑，存在展示合同漂移风险；
- 检索、判定、长文本、列表型节点没有统一的产品级展示规则。

本设计用于收敛 KB Chat 右侧节点详情，使其只展示**关键、不冗余、对用户可读**的信息。

## 2. 目标

### 2.1 核心目标

1. 每个 live 节点都展示“关键输入 / 关键输出”。
2. 展示合同以**后端单一真值源**为准，前端只负责渲染。
3. 不再将原始 `snapshot` / JSON dump / 通用调试摘要直接暴露给用户。
4. 列表型结果逐项完整展示，长文本全文展示。
5. 判定类节点统一只展示“结论 + 原因 + 下一跳”。
6. 证据产出型检索节点统一只展示“文档名 + chunk 内容”，不展示分数、rank、置信度等技术细节。

### 2.2 非目标

- 不在本轮重构 trace 状态机、stage 分组或节点拓扑。
- 不新增新的 live 节点。
- 不为右侧详情新增“展开 JSON”“原始快照”“调试模式”等双层 UI。
- 不将内部指标字段继续包装后暴露给用户。

## 3. 设计结论

### 3.1 责任边界

#### 后端

后端在 `backend/src/app/agents/kb_chat_trace_nodes.py` 中为每个 live 节点产出最终展示合同。

说明：

- **概念层**仍称“关键输入 / 关键输出”；
- **现有 wire contract 字段名保持不变**，继续使用：
  - `display_input_items`
  - `display_output_items`
- 本 spec **不要求**将 SSE / typings / 前端字段名从 `*_items` 改成 `display_input` / `display_output`。

后端负责：

- 按节点定义白名单；
- 控制字段顺序；
- 在 node_io 发射前完成所有面向用户的中文化与业务化映射；
- 在缺少最小可读字段时生成默认可读文案；
- 确保 SSE / node_io / 右侧详情读取到的是同一份展示结果。

#### 前端

前端只消费后端最终合同并做固定版式渲染，不再自行猜测某节点该显示哪些字段。

前端负责：

- 固定渲染“关键输入”“关键输出”两块；
- 按后端给定顺序逐项显示；
- 列表逐项完整换行显示；
- 长文本直接全文显示；
- 当某块为空时显示“暂无关键输入”/“暂无关键输出”。

### 3.2 展示合同原则

1. **强收敛模式**：每个节点只展示关键输入与关键输出，不提供原始细节兜底。
2. **列表型结果**：拆分后逐项完整展示，不做“仅数量”“仅摘要”替代。
3. **长文本结果**：完整显示全文，不只显示首段。
4. **判定类节点**：输出统一只展示“结论 + 原因 + 下一跳”。
5. **证据产出型检索节点**：输出统一只展示“文档名 + chunk 内容”。
6. **检索规划 / 分发节点**：输出展示计划或分发结果，不强制伪装成证据列表。
7. **汇总/子图节点**：不重复展示下游叶子节点已经完整展示的长列表，仅展示本节点自己的结论/原因/下一跳。
8. **例外**：承担 fan-in 语义收敛的证据聚合节点（如 `merge_subquery_context`、`context_compress`）允许输出“聚合后的 canonical 证据列表”，因为该列表本身就是该节点的新结果，而非简单重复下游叶子节点。
9. **不依赖通用 fallback**：某节点若缺少展示合同，应补齐该节点定义，而不是回退展示原始 JSON。

## 4. 数据合同

右侧详情只认 node_io 中的最终展示项，且沿用当前实际字段名：

```json
{
  "display_input_items": [
    { "key": "user_input", "label": "用户问题", "value": "..." }
  ],
  "display_output_items": [
    { "key": "decision", "label": "结论", "value": "复杂问题" },
    { "key": "reason", "label": "原因", "value": "涉及多概念比较与方法边界" },
    { "key": "next_node_label", "label": "下一跳", "value": "问题分解" }
  ]
}
```

约束：

- `key`：稳定键，供测试与选择器使用；
- `label`：面向用户的中文标签；
- `value`：支持字符串或字符串数组；
- 数组值用于逐项完整展示；
- UI 概念上可称“关键输入 / 关键输出”，但实现上继续从 `display_input_items` / `display_output_items` 读取；
- 不再将原始 `snapshot` / `summary` / JSON dump 当作默认 UI 数据源。

### 4.1 下一跳显示规则

- `next_node` / `route_to` / `goto` 若用于右侧详情展示，必须先转换为**中文节点名**；
- 不直接向用户展示内部 node id（如 `decomposition`、`doc_gate_route`）；
- 中文化在**后端 node_io 发射层**完成，前端不再负责把 `next_node` 转成中文；
- 后端解析顺序固定为：`KB_CHAT_NODE_METADATA.label` -> graph schema metadata.label -> 业务化兜底文案；
- 若无法解析中文名，则使用最接近的业务化中文文案，如“结束”“继续检索”“进入答案生成”；
- 仅在测试与内部选择器里继续使用稳定 key，不将内部 id 暴露到 UI 文案。

### 4.2 检索证据展示形态

由于当前 `ChatNodeDisplayItem.value` 类型为 `string | string[]`，本轮检索类节点统一采用：

- 一个 display item，`value` 为 `string[]`；
- 数组每一项代表一条证据命中；
- 每一项格式固定为：

```text
文档名：<document title>
Chunk 内容：<chunk text>
```

约束：

- 不拆成“文档名 item + chunk item”两个独立 item，避免丢失配对关系；
- 不附带 score / rank / 来源路径 / 检索技术指标；
- 若文档标题缺失，统一显示：`未命名文档`；
- 若 chunk 正文缺失，统一显示：`正文缺失`；
- 无证据时使用明确业务文案，如“未检索到相关证据”。

`current_evidence` 作为 judge / generate 节点的输入时，**完全复用** `retrieved_evidence` / `compressed_evidence` 的展示形态：

- `value` 仍为 `string[]`
- 每项仍采用：

```text
文档名：<document title>
Chunk 内容：<chunk text>
```

- 不因节点家族不同改成其他输入格式
- 不允许在 judge / generate 节点临时发明新的证据字符串拼装规则

### 4.3 列表值中文化规则

以下列表值同样属于面向用户展示合同，必须在后端 emission 层完成中文化 / 业务化，不允许把内部 id 原样透传到 UI：

- `dispatch_targets`
  - 例如：`doc_gate_sufficiency` -> `证据充分度`
- `review_checks`
  - 例如：`citation` -> `引用覆盖审查`
  - 例如：`factual` -> `事实正确性审查`
- 其他将来新增的“节点名列表”“检查项列表”“分支目标列表”
  - 一律遵循相同规则

### 4.4 Canonical key 规则

本轮将“面向 UI 的 display item key”视为稳定合同，并统一收敛为以下命名：

- 双向通用
  - `user_input`
  - `recent_turns`
  - `merged_context`
  - `normalized_query`
  - `query_items`
  - `draft_answer`
  - `current_evidence`
  - `subquery`
  - `exit_action`
  - `candidate_answer`
  - `gate_results`
  - `review_results`
- 判定类输出
  - `decision`
  - `reason`
  - `next_node_label`
- 提示类输出
  - `clarification_prompt`
- 分发/列表输出
  - `dispatch_targets`
  - `sub_queries`
  - `multi_queries`
  - `review_checks`
- 检索规划输出
  - `planned_query_count`
  - `planned_per_query_top_k`
- 聚合判定输出
  - `gate_results`
  - `review_results`
- 证据输出
  - `retrieved_evidence`
  - `compressed_evidence`
- 长文本输出
  - `hyde_docs`
  - `draft_answer`
  - `repaired_answer`
  - `final_answer`
- 错误输出
  - `error_summary`

明确规则：

- 当前内部快照字段如 `checks`、`query_count`、`best_answer` 可以继续存在于内部状态中；
- 但进入 `display_input_items` / `display_output_items` 后，应统一映射到上面的 canonical key；
- 例如：
  - `checks` -> `review_checks`
  - `query_count` -> `planned_query_count`
  - `per_query_top_k` -> `planned_per_query_top_k`
  - `best_answer` -> `final_answer`
  - `doc_gate_*` 判定结果集合 -> `gate_results`
  - `answer_review_*` 判定结果集合 -> `review_results`

`gate_results` / `review_results` 的序列化形态统一为 `string[]`，逐项完整展示。例如：

```text
证据充分度：通过｜原因：证据覆盖问题关键实体
可回答性：通过｜原因：证据已覆盖比较维度
证据冲突检测：未通过｜原因：两份材料给出相反结论
```

```text
引用覆盖审查：通过｜原因：关键断言均有引用
事实正确性审查：未通过｜原因：第二段与证据不一致
可回答性审查：通过｜原因：已直接回答用户问题
```

### 4.5 规范性示例 payload

#### 示例 A：判定节点（`complexity_classify`）

```json
{
  "node_name": "complexity_classify",
  "phase": "end",
  "display_input_items": [
    { "key": "user_input", "label": "用户问题", "value": "解释 CoT 和 ToT 的区别" }
  ],
  "display_output_items": [
    { "key": "decision", "label": "结论", "value": "复杂问题" },
    { "key": "reason", "label": "原因", "value": "涉及方法比较与边界说明" },
    { "key": "next_node_label", "label": "下一跳", "value": "问题分解" }
  ]
}
```

#### 示例 B：分发节点（`doc_gate_dispatch`）

```json
{
  "node_name": "doc_gate_dispatch",
  "phase": "end",
  "display_input_items": [
    { "key": "normalized_query", "label": "规范化问题", "value": "解释 CoT 和 ToT 的区别" },
    {
      "key": "current_evidence",
      "label": "当前证据",
      "value": ["文档名：Agent Design.pdf\nChunk 内容：CoT 关注线性推理，ToT 允许树状探索。"]
    }
  ],
  "display_output_items": [
    {
      "key": "dispatch_targets",
      "label": "派发目标",
      "value": ["证据充分度", "可回答性", "证据冲突检测"]
    }
  ]
}
```

#### 示例 C：失败节点（`retrieve`）

```json
{
  "node_name": "retrieve",
  "phase": "error",
  "display_input_items": [
    {
      "key": "query_items",
      "label": "检索查询项",
      "value": ["1. CoT 与 ToT 区别"]
    }
  ],
  "display_output_items": [
    { "key": "error_summary", "label": "错误信息", "value": "节点执行失败" }
  ]
}
```

## 5. 节点展示白名单

以下为本轮确认的节点级展示规则。

约束：

- 每个节点条目中列出的输入/输出顺序，就是右侧详情最终渲染顺序；
- 若同一节点同时有“基础字段 + 例外字段”（如 `decision` 后追加 `clarification_prompt`），则按条目中出现顺序展示；
- 标签采用条目中的中文语义，不允许实现阶段自行发明新的面向用户标签。

### 5.1 预处理层

- `preprocess_subgraph`
  - 输入：`user_input`
  - 输出：`decision`、`reason`、`next_node_label`
- `merge_context`
  - 输入：`user_input`；若存在上下文，再附 `recent_turns`
  - 输出：`merged_context`
- `coref_rewrite`
  - 输入：`user_input`
  - 输出：`normalized_query`
- `ambiguity_check`
  - 输入：`normalized_query`
  - 输出：`decision`、`reason`、`clarification_prompt`
  - 若需要澄清：附 `clarification_prompt` 全文
- `normalize_rewrite`
  - 输入：`normalized_query`
  - 输出：`normalized_query`

### 5.2 路由 / 扩展层

- `complexity_classify`
  - 输入：`user_input`
  - 输出：`decision`、`reason`、`next_node_label`
- `generate_variants_mod`
  - 输入：`normalized_query`
  - 输出：`multi_queries`（逐项完整展示）
- `decomposition`
  - 输入：`normalized_query`
  - 输出：`sub_queries`（逐项完整展示）
- `generate_variants`
  - 输入：`normalized_query`
  - 输出：`multi_queries`（逐项完整展示）
- `entity_expand`
  - 输入：`normalized_query`
  - 输出：`multi_queries`（逐项完整展示）
- `hyde`
  - 输入：`normalized_query`
  - 输出：`hyde_docs`（逐项全文展示；若只有一条则数组长度为 1）
- `prepare_messages`
  - 输入：`normalized_query` + `sub_queries` / `multi_queries`
  - 输出：`query_items`（逐项完整展示）
- `preprocess_exit`
  - 输入：`normalized_query`
  - 输出：`decision`、`reason`、`next_node_label`
  - 若直接产出答复：附 `final_answer` 全文

### 5.3 检索层

- `retrieval_subgraph`（检索流程汇总节点）
  - 输入：`query_items`
  - 输出：`decision`、`reason`、`next_node_label`
- `retrieval_budget_plan`（检索规划节点）
  - 输入：`normalized_query` + `query_items`
  - 输出：`planned_query_count`、`planned_per_query_top_k`
- `dispatch_subqueries`（检索分发节点）
  - 输入：`query_items`
  - 输出：`dispatch_targets`（逐项完整展示）
- `retrieve_subquery`
  - 输入：`subquery`
  - 输出：`retrieved_evidence`（按单条证据组合为一个字符串数组项）
- `merge_subquery_context`
  - 输入：`retrieved_evidence`（内部 fan-in）
  - 输出：`retrieved_evidence`（按单条证据组合为一个字符串数组项）
- `retrieve`
  - 输入：`query_items`
  - 输出：`retrieved_evidence`（按单条证据组合为一个字符串数组项）
- `context_compress`
  - 输入：`retrieved_evidence`
  - 输出：`compressed_evidence`（按单条证据组合为一个字符串数组项）

### 5.4 Judge（证据门控）层

判定类统一遵循“结论 + 原因 + 下一跳”。

例外：

- `doc_gate_dispatch` 是分发节点，不强制套用“结论 + 原因 + 下一跳”，其输出以“派发目标”作为关键结果；
- 其他纯列表/分发节点若后续补入，也应在实现与测试中显式标注为例外。
- `evidence_gate_subgraph`
  - 输入：`normalized_query` + `current_evidence`
  - 输出：`decision`、`reason`、`next_node_label`
- `doc_gate_dispatch`
  - 输入：`normalized_query` + `current_evidence`
  - 输出：`dispatch_targets`
- `doc_gate_sufficiency`
  - 输入：`current_evidence`
  - 输出：`decision`、`reason`、`next_node_label`
- `doc_gate_answerability`
  - 输入：`current_evidence`
  - 输出：`decision`、`reason`、`next_node_label`
- `doc_gate_conflict`
  - 输入：`current_evidence`
  - 输出：`decision`、`reason`、`next_node_label`
- `doc_gate_fuse`
  - 输入：`gate_results`
  - 输出：`decision`、`reason`、`next_node_label`
- `doc_gate_route`
  - 输入：`normalized_query` + 门控融合结果
  - 输出：`decision`、`reason`、`next_node_label`

### 5.5 Answer（生成）层

- `transform_query`
  - 输入：`normalized_query`
  - 输出：`normalized_query`
- `answer_subgraph`
  - 输入：`normalized_query` + `current_evidence`
  - 输出：`decision`、`reason`、`next_node_label`
- `draft_generate`
  - 输入：`normalized_query` + `current_evidence`
  - 输出：`draft_answer`（全文显示）
- `answer_repair`
  - 输入：`draft_answer`
  - 输出：`repaired_answer`（全文显示）
- `answer_commit`
  - 输入：`candidate_answer`
  - 输出：`final_answer`（全文显示）

### 5.6 Review（审查）层

- `answer_review_dispatch`
  - 输入：`draft_answer`
  - 输出：`review_checks`（逐项完整展示）
- `answer_review_citation`
  - 输入：`draft_answer`
  - 输出：`decision`、`reason`、`next_node_label`
- `answer_review_factual`
  - 输入：`draft_answer`
  - 输出：`decision`、`reason`、`next_node_label`
- `answer_review_answerability`
  - 输入：`draft_answer`
  - 输出：`decision`、`reason`、`next_node_label`
- `answer_review_fuse`
  - 输入：`review_results`
  - 输出：`decision`、`reason`、`next_node_label`
- `cove_check`
  - 输入：`draft_answer`
  - 输出：`decision`、`reason`、`next_node_label`
- `chain_of_verification`
  - 输入：`draft_answer`
  - 输出：`decision`、`reason`、`next_node_label`
- `claim_citation_check`
  - 输入：`draft_answer`
  - 输出：`decision`、`reason`、`next_node_label`

### 5.7 Finalize（收口）层

- `confidence_calibrate`
  - 输入：`final_answer`
  - 输出：`decision`、`reason`、`next_node_label`
  - “结论”只展示最终置信等级，不展示分数
- `force_exit`
  - 输入：`exit_action` + `candidate_answer`
  - 输出：`final_answer`、`reason`、`next_node_label`
  - `next_node_label` 固定为 `结束`

## 6. 右侧详情渲染规则

右侧详情统一为固定结构：

1. 节点头部
   - 节点中文名
   - 当前状态（进行中 / 已完成 / 失败 / 待补充）
2. 关键输入
   - 严格按后端 `display_input_items` 顺序渲染
   - 单条文本全文显示
   - 列表逐项完整换行显示
3. 关键输出
   - 严格按后端 `display_output_items` 顺序渲染
   - 判定类统一为“结论 / 原因 / 下一跳”

状态映射固定为：

- `idle` -> `待执行`
- `running` -> `进行中`
- `completed` -> `已完成`
- `failed` -> `失败`
- `waiting_user` -> `待补充`
- `skipped` -> `已跳过`

不再展示：

- `input_summary`
- `output_summary`
- 原始 `snapshot`
- JSON dump
- `score` / `confidence` / `signals` / `fallback_reason` 等内部排障字段

唯一例外：若某字段本身已被上面白名单定义为“关键输出”，则可展示其业务化版本。

## 7. 缺失字段策略

### 7.1 单字段缺失

- 单条字段为空：该条不展示。

### 7.2 整组缺失

- 某节点没有关键输入：显示“暂无关键输入”。
- 某节点没有关键输出：显示“暂无关键输出”。
- 不允许用原始 JSON / 快照回退填充 UI。

### 7.3 判定节点最小可读性兜底

若判定类节点缺少必要字段，后端应补最小可读文案：

- 原因：`未返回明确原因`
- 下一跳：`结束` 或 `下游节点未知`

这类兜底只用于补“面向用户的最小可读表达”，不允许退回内部指标字段。

### 7.4 失败节点展示策略

- 失败态以 **error-phase `node_io` 事件自身为完整合同**；
- 前端不负责把 start / end / error 多个事件拼接成一个详情面板；
- 因此 error-phase payload 必须重复携带右侧详情所需的 `display_input_items`，并在 `display_output_items` 中追加错误项；
- 失败节点仍保留“关键输入”展示；
- “关键输出”允许追加一条用户可读错误项：
  - `key = error_summary`
  - `label = 错误信息`
  - `value = 用户可读错误摘要`
- 允许展示 `error_summary`，但不允许展示原始异常栈、Python traceback、内部调试对象；
- 若后端未提供 `error_summary`，则显示统一文案：`节点执行失败`；
- 失败态不因为缺少正常输出而回退显示原始 JSON。

## 8. 实现边界与改动落点

### 8.1 后端主改动

- `backend/src/app/agents/kb_chat_trace_nodes.py`
  - 重写/收紧每个节点的 `display_input_items` / `display_output_items`
  - 清理面向 UI 的通用冗余 fallback
  - 为缺少 `reason` / `next_node` 的判定节点补最小可读文案
  - 为检索结果统一提炼“文档名 + chunk 内容”

### 8.2 前端配套改动

- `frontend/src/services/kbChatFlowSelectors.ts`
  - 从“挑字段 + 风险提示补充”收敛为“只消费后端最终合同”
- `frontend/src/components/chat/KbChatFlowPanel.tsx`
  - 只负责固定版式渲染
  - 去掉 JSON / 原始 fallback 展示路径

### 8.3 兼容性约束

- 保留现有 `state` SSE 作为运行态真值；
- 本轮不修改节点目录、stage 编排与状态来源；
- 本轮只收敛右侧详情的内容合同与渲染行为。

## 9. 错误处理与风险

### 9.1 风险

- 后端节点定义集中后，`kb_chat_trace_nodes.py` 会继续变大；
- 个别节点当前可能缺少直接可用的 `reason` / `next_node`，需要按业务语义补默认文案；
- 检索节点可能同时存在多种证据结构，需要统一抽取逻辑。

### 9.2 应对

- 保持“单节点一组清晰白名单”，避免继续追加全局 fallback；
- 优先按节点家族分段收敛，避免零散补丁；
- 为节点展示合同补测试，防止未来回流调试字段。

## 10. 验收标准

1. 当前 live 节点都能看到“关键输入 / 关键输出”。
2. 不再出现面向用户的原始 JSON 快照。
3. `complexity_classify`
   - 输入只看用户问题
   - 输出只看分类结果 / 原因 / 下一跳
4. 列表节点（如 `decomposition`、`generate_variants*`、`prepare_messages`、`answer_review_dispatch`）
   - 逐项完整展示
5. 长文本节点（如 `hyde`、`draft_generate`、`answer_repair`、`answer_commit`）
   - 全文展示
6. 证据产出型检索节点（如 `retrieve*`、`merge_subquery_context`、`context_compress`）
   - 只展示文档名 + chunk 内容
   - 不展示分数 / rank / 技术指标
7. 检索规划 / 分发节点（如 `retrieval_budget_plan`、`dispatch_subqueries`）
   - 分别展示规划结果或分发结果
   - 不伪装成证据列表
8. 判定节点
   - 统一只展示结论 + 原因 + 下一跳
   - 不展示 score / confidence / signals

## 11. 最小验证建议

- 后端：
  - 补充 `backend/src/app/agents/kb_chat_trace_nodes.py` 对应的节点展示合同定向 pytest；
  - 补充 emitted `node_io` 合同测试，至少验证 `wrap_kb_chat_node_with_io` -> `KbChatService._build_node_io_payload` 这一发射链路确实携带 `display_input_items` / `display_output_items` / `error_summary`；
  - 至少覆盖一个判定节点、一个检索节点、一个长文本节点、一个失败节点；
- 前端：
  - 补充 `frontend/src/services/kbChatFlowSelectors.test.ts`，验证 selector 只消费 `display_input_items` / `display_output_items`；
  - 补充 `frontend/src/components/chat/KbChatFlowPanel.test.ts`，验证“无 JSON fallback、列表逐项展示、失败节点显示错误摘要”；
  - 补充空态校验：`暂无关键输入` / `暂无关键输出`；
  - 运行 `npm run typecheck`；
- 如改动范围涉及实际 selector / panel 渲染，再补最小必要构建验证。

## 12. 规范化 key 附录（首版）

为减少实现漂移，首版允许的 display key 收敛如下：

| Key | 角色 | 说明 |
|---|---|---|
| `user_input` | 输入 | 原始用户问题 |
| `recent_turns` | 输入 | 最近对话列表 |
| `merged_context` | 输入/输出 | 合并后的上下文 |
| `normalized_query` | 输入/输出 | 规范化或改写后的问题 |
| `query_items` | 输入/输出 | 检索查询项列表 |
| `draft_answer` | 输入/输出 | 草稿答案 |
| `current_evidence` | 输入 | 当前证据列表 |
| `subquery` | 输入 | 单个分支查询 |
| `exit_action` | 输入 | 提前终止动作 |
| `candidate_answer` | 输入 | 终止前候选答案 |
| `gate_results` | 输入 | 门控判定结果集合 |
| `review_results` | 输入 | 审查结果集合 |
| `decision` | 输出 | 判定结论 |
| `reason` | 输出 | 判定原因或终止原因 |
| `next_node_label` | 输出 | 已中文化的下一跳节点名 |
| `clarification_prompt` | 输出 | 歧义澄清提示全文 |
| `dispatch_targets` | 输出 | 已中文化的派发目标列表 |
| `sub_queries` | 输出 | 子问题列表 |
| `multi_queries` | 输出 | 多路查询列表 |
| `review_checks` | 输出 | 已中文化的审查项列表 |
| `planned_query_count` | 输出 | 检索计划中的查询数量 |
| `planned_per_query_top_k` | 输出 | 检索计划中的每路召回条数 |
| `retrieved_evidence` | 输入/输出 | 检索命中的“文档名 + chunk 内容”列表 |
| `compressed_evidence` | 输出 | 压缩后保留的“文档名 + chunk 内容”列表 |
| `hyde_docs` | 输出 | HyDE 生成文本列表，逐项全文展示 |
| `repaired_answer` | 输出 | 修复后答案全文 |
| `final_answer` | 输出 | 最终答案或提前终止答复全文 |
| `error_summary` | 输出 | 用户可读错误摘要 |

## 13. 后续阶段

本 spec 通过 review 并经用户审阅后，下一阶段进入 implementation plan，拆分为：

1. 后端节点展示合同收敛；
2. 前端 selector / panel 渲染收口；
3. 节点合同测试与最小验收。
