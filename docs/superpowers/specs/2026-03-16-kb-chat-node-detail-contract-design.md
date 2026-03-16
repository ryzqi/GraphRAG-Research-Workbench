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
6. 检索类节点统一只展示“文档名 + chunk 内容”，不展示分数、rank、置信度等技术细节。

### 2.2 非目标

- 不在本轮重构 trace 状态机、stage 分组或节点拓扑。
- 不新增新的 live 节点。
- 不为右侧详情新增“展开 JSON”“原始快照”“调试模式”等双层 UI。
- 不将内部指标字段继续包装后暴露给用户。

## 3. 设计结论

### 3.1 责任边界

#### 后端

后端在 `backend/src/app/agents/kb_chat_trace_nodes.py` 中为每个 live 节点产出最终展示合同：

- `display_input`
- `display_output`

后端负责：

- 按节点定义白名单；
- 控制字段顺序；
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
5. **检索类节点**：输出统一只展示“文档名 + chunk 内容”。
6. **汇总/子图节点**：不重复展示下游叶子节点已经完整展示的长列表，仅展示本节点自己的结论/原因/下一跳。
7. **不依赖通用 fallback**：某节点若缺少展示合同，应补齐该节点定义，而不是回退展示原始 JSON。

## 4. 数据合同

右侧详情只认 node_io 中的最终展示项：

```json
{
  "display_input": [
    { "key": "user_input", "label": "用户问题", "value": "..." }
  ],
  "display_output": [
    { "key": "decision", "label": "结论", "value": "复杂问题" },
    { "key": "reason", "label": "原因", "value": "涉及多概念比较与方法边界" },
    { "key": "next_node", "label": "下一跳", "value": "decomposition" }
  ]
}
```

约束：

- `key`：稳定键，供测试与选择器使用；
- `label`：面向用户的中文标签；
- `value`：支持字符串或字符串数组；
- 数组值用于逐项完整展示；
- 不再将原始 `snapshot` / `summary` / JSON dump 当作默认 UI 数据源。

## 5. 节点展示白名单

以下为本轮确认的节点级展示规则。

### 5.1 预处理层

- `preprocess_subgraph`
  - 输入：用户问题
  - 输出：结论（采用的预处理策略）、原因、下一跳
- `merge_context`
  - 输入：当前问题；若存在上下文，再附最近对话
  - 输出：合并后上下文
- `coref_rewrite`
  - 输入：输入问题
  - 输出：改写后问题
- `ambiguity_check`
  - 输入：输入问题
  - 输出：结论（是否需要澄清）、原因
  - 若需要澄清：附澄清提示全文
- `normalize_rewrite`
  - 输入：输入问题
  - 输出：规范化问题

### 5.2 路由 / 扩展层

- `complexity_classify`
  - 输入：用户问题
  - 输出：分类结果、原因、下一跳
- `generate_variants_mod`
  - 输入：规范化问题
  - 输出：多路查询（逐项完整展示）
- `decomposition`
  - 输入：规范化问题
  - 输出：子问题列表（逐项完整展示）
- `generate_variants`
  - 输入：规范化问题
  - 输出：多路查询（逐项完整展示）
- `entity_expand`
  - 输入：规范化问题
  - 输出：多路查询（逐项完整展示）
- `hyde`
  - 输入：规范化问题
  - 输出：HyDE 生成文本（全文展示）
- `prepare_messages`
  - 输入：主问题 + 子问题/多路查询
  - 输出：检索查询项（逐项完整展示）
- `preprocess_exit`
  - 输入：规范化问题
  - 输出：结论、原因、下一跳
  - 若直接产出答复：附答复全文

### 5.3 检索层

- `retrieval_subgraph`
  - 输入：检索查询项
  - 输出：结论、原因、下一跳
- `retrieval_budget_plan`
  - 输入：主问题 + 查询项
  - 输出：检索计划（分支数、每路召回条数）
- `dispatch_subqueries`
  - 输入：查询项
  - 输出：分支查询列表（逐项完整展示）
- `retrieve_subquery`
  - 输入：单个分支查询
  - 输出：文档名 + chunk 内容
- `merge_subquery_context`
  - 输入：各分支证据结果
  - 输出：合并后的文档名 + chunk 内容
- `retrieve`
  - 输入：主查询/查询项
  - 输出：文档名 + chunk 内容
- `context_compress`
  - 输入：原始证据列表
  - 输出：压缩后保留的文档名 + chunk 内容

### 5.4 Judge（证据门控）层

判定类统一遵循“结论 + 原因 + 下一跳”：

- `evidence_gate_subgraph`
  - 输入：问题 + 当前证据
  - 输出：结论、原因、下一跳
- `doc_gate_dispatch`
  - 输入：问题 + 当前证据
  - 输出：派发目标
- `doc_gate_sufficiency`
  - 输入：当前证据
  - 输出：结论、原因、下一跳
- `doc_gate_answerability`
  - 输入：当前证据
  - 输出：结论、原因、下一跳
- `doc_gate_conflict`
  - 输入：当前证据
  - 输出：结论、原因、下一跳
- `doc_gate_fuse`
  - 输入：各门控判定结果
  - 输出：结论、原因、下一跳
- `doc_gate_route`
  - 输入：问题 + 门控融合结果
  - 输出：结论、原因、下一跳

### 5.5 Answer（生成）层

- `transform_query`
  - 输入：当前问题
  - 输出：改写后问题
- `answer_subgraph`
  - 输入：问题 + 当前证据
  - 输出：结论、原因、下一跳
- `draft_generate`
  - 输入：问题 + 当前证据
  - 输出：答案草稿（全文显示）
- `answer_repair`
  - 输入：修复前答案
  - 输出：修复后答案（全文显示）
- `answer_commit`
  - 输入：候选最终答案
  - 输出：最终提交答案（全文显示）

### 5.6 Review（审查）层

- `answer_review_dispatch`
  - 输入：待审查答案
  - 输出：审查项列表（逐项完整展示）
- `answer_review_citation`
  - 输入：待审查答案
  - 输出：结论、原因、下一跳
- `answer_review_factual`
  - 输入：待审查答案
  - 输出：结论、原因、下一跳
- `answer_review_answerability`
  - 输入：待审查答案
  - 输出：结论、原因、下一跳
- `answer_review_fuse`
  - 输入：各审查项结果
  - 输出：结论、原因、下一跳
- `cove_check`
  - 输入：待验证答案
  - 输出：结论、原因、下一跳
- `chain_of_verification`
  - 输入：待验证答案
  - 输出：结论、原因、下一跳
- `claim_citation_check`
  - 输入：待验证答案
  - 输出：结论、原因、下一跳

### 5.7 Finalize（收口）层

- `confidence_calibrate`
  - 输入：最终答案
  - 输出：结论、原因、下一跳
  - “结论”只展示最终置信等级，不展示分数
- `force_exit`
  - 输入：终止动作 / 当前候选答案
  - 输出：终止答复全文 + 原因
  - 如需统一可将“下一跳”固定为“结束”

## 6. 右侧详情渲染规则

右侧详情统一为固定结构：

1. 节点头部
   - 节点中文名
   - 当前状态（进行中 / 已完成 / 失败 / 待补充）
2. 关键输入
   - 严格按后端 `display_input` 顺序渲染
   - 单条文本全文显示
   - 列表逐项完整换行显示
3. 关键输出
   - 严格按后端 `display_output` 顺序渲染
   - 判定类统一为“结论 / 原因 / 下一跳”

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

## 8. 实现边界与改动落点

### 8.1 后端主改动

- `backend/src/app/agents/kb_chat_trace_nodes.py`
  - 重写/收紧每个节点的 `display_input` / `display_output`
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
6. 检索节点（如 `retrieve*`、`merge_subquery_context`、`context_compress`）
   - 只展示文档名 + chunk 内容
   - 不展示分数 / rank / 技术指标
7. 判定节点
   - 统一只展示结论 + 原因 + 下一跳
   - 不展示 score / confidence / signals

## 11. 最小验证建议

- 后端：补充节点展示合同的定向 pytest；
- 前端：定向单测 + `npm run typecheck`；
- 如改动范围涉及实际 selector / panel 渲染，再补最小必要构建验证。

## 12. 后续阶段

本 spec 通过 review 并经用户审阅后，下一阶段进入 implementation plan，拆分为：

1. 后端节点展示合同收敛；
2. 前端 selector / panel 渲染收口；
3. 节点合同测试与最小验收。
