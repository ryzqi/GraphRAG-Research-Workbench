# Findings

## 会话初始化

- 2026-04-20：仓库根当前存在 `AGENTS.md` 与 `上下文优化方案.md`，尚无 `task_plan.md`、`findings.md`、`progress.md`。
- 2026-04-20：`git status --short --branch` 显示当前分支为 `master`，并存在用户未提交改动：
  - `D docs/api_contract_research.md`
  - `D docs/architecture.md`
  - `?? 上下文优化方案.md`
- 2026-04-20：本轮任务是 backend-only，上线前需要读取 `backend/graphify-out/GRAPH_REPORT.md` 并在 backend 修改后重建图谱。

## Memory 速记

- 历史经验显示执行 backend 计划时应保持 task-scoped、先验证再改、每个任务单独提交。
- 历史经验还提示计划文件可能过时，实际路径/类名/调用链必须回到当前源码核对。

## 第一个点 P0-1 代码取证

- `backend/src/app/core/settings.py`
  - 当前已有 `llm_max_input_tokens`、`context_history_max_tokens`、`context_tool_max_tokens`，默认值均为 `None`。
  - 当前缺少 `context_retrieval_max_tokens`。
- `backend/src/app/integrations/langchain_profiles.py`
  - `build_chat_model_profile()` 直接消费 `settings.llm_max_input_tokens`。
  - 当该值为空或 `<= 0` 时返回 `None`；一旦给出正默认值，就会真正向 LangChain 传入 `{"max_input_tokens": ...}`。
- `backend/src/app/services/general_chat_service_runtime.py`
  - `_build_summary_trigger()` 发现 `llm_max_input_tokens` 为真时，会切换到 `SUMMARY_TRIGGER`（fraction 模式），否则退回 messages/tokens 阈值。
  - 因此本点虽然看似“配置”，但默认值变化会带来 General Chat 摘要触发策略变化。
- `backend/src/app/services/context_builder.py`
  - `context_history_max_tokens`、`context_tool_max_tokens` 已经实际参与裁剪。
  - `build_metrics()` 当前 budgets 只输出 `history_messages/history_tokens/summary_tokens/tool_tokens`，没有 `llm_input_tokens` 与 `retrieval_tokens`。
  - 新增 `context_retrieval_max_tokens` 后，若不至少透传到 budgets，字段会在当前点完全悬空。

## 外部调研

- LangChain 官方 `built-in middleware` 文档说明：
  - `SummarizationMiddleware` 支持 `trigger=("fraction", x)`、`("tokens", n)`、`("messages", n)`，并依赖上下文大小信息控制摘要触发。
  - `ContextEditingMiddleware` 用于在 token 压力下清理旧工具结果，体现“预算先行”的治理思路。
- LangChain 官方 `context engineering` 文档强调：
  - 需要显式管理模型可见上下文，把长期状态写出 prompt，再按预算选回必要部分。
- Anthropic 官方长上下文建议强调：
  - 长任务应分阶段、显式保留中间状态，而不是让 prompt 无上限膨胀。

## 测试入口判断

- `backend/pyproject.toml` 指定 `pytest` 的 `testpaths = ["tests"]`，但 `backend/tests/` 当前为空。
- 本点需要新建一个最小测试文件作为 RED/GREEN 入口，适合覆盖：
  - `Settings` 类字段默认值；
  - `build_chat_model_profile()` 的默认行为；
  - `ContextBuilder.build_metrics()` 是否暴露新增预算键。

## 待补充

- 定向验证命令及结果。

## 第二个点 P0-2 代码取证

- `backend/src/app/agents/general_chat_agent.py`
  - General Chat 使用 `create_agent`，当前 middleware 只有 `SummarizationMiddleware` 和可选 `HumanInTheLoopMiddleware`。
  - 适合直接引入 LangChain 官方 `ContextEditingMiddleware` + `ClearToolUsesEdit`。
- `backend/src/app/services/general_chat_service_execution.py`
  - 非流式 answer 两处构造 General Chat agent：正常路径与 previous_response_id recovery 路径。
- `backend/src/app/services/general_chat_service_streaming_ops.py`
  - 流式 answer 与 tool approval resume stream 各构造一次 General Chat agent。
- `backend/src/app/services/general_chat_service_resume_ops.py`
  - 非流式 tool approval resume 构造一次 General Chat agent。
- `backend/src/app/services/context_builder.py`
  - KB Chat 或自建上下文路径仍依赖 `build_tool_context()` 和 `context_tool_max_tokens`，本点不改变该逻辑。

## 第二个点 P0-2 外部调研

- LangChain 官方 Python 文档示例显示 `ContextEditingMiddleware(edits=[ClearToolUsesEdit(...)])` 可作为 `create_agent(..., middleware=[...])` 的 middleware 项。
- 本地包 introspection 确认当前安装版本签名：
  - `ContextEditingMiddleware(*, edits: Iterable[ContextEdit] | None = None, token_count_method='approximate')`
  - `ClearToolUsesEdit(trigger=100000, clear_at_least=0, keep=3, clear_tool_inputs=False, exclude_tools=(), placeholder='[cleared]')`

## 第二个点 P0-2 验证

- RED：`uv run pytest tests/test_general_chat_context_editing.py` 起初失败，原因是 `build_general_chat_agent()` 不接受 `tool_context_trigger_tokens`。
- GREEN：`uv run pytest tests/test_general_chat_context_editing.py tests/test_context_budget_settings.py` 最终 `6 passed`。

## 第三个点 P0-3 代码取证

- `backend/src/app/agents/general_chat_agent.py`
  - `SummarizationMiddleware` 已存在，但 `keep` 原先硬编码为 `SUMMARY_KEEP=("messages", 20)`。
  - 当前 LangChain 版本的 `SummarizationMiddleware` 支持 `trim_tokens_to_summarize` 参数。
- `backend/src/app/services/general_chat_service_runtime.py`
  - `_build_summary_trigger()` 已根据 `llm_max_input_tokens` 决定 fraction 触发或 messages/tokens 触发。
  - 当所有 trigger 关闭时，原先回退到硬编码 `SUMMARY_KEEP[1]`。
- `backend/src/app/services/conversation_summary_service.py`
  - 持久摘要服务依赖 `summary_enabled`。
  - `_should_update()` 使用 `summary_trigger_min_messages` / `summary_trigger_min_tokens`。
  - `_summarize_with_langmem()` 原先固定 `max_tokens_before_summary=0`。
- `backend/src/app/agents/kb_chat_agentic/preprocess_context_helpers.py`
  - KB Chat preprocess 的函数级摘要也调用 `langmem.short_term.summarize_messages`，原先同样固定 `max_tokens_before_summary=0`。

## 第三个点 P0-3 外部调研

- LangChain 官方文档确认 `SummarizationMiddleware` 支持 `trigger`、`keep` 与 `trim_tokens_to_summarize`。
- 本地包 introspection 确认当前安装版本签名包含 `trim_tokens_to_summarize: int | None = 4000`。
- 因为完整替换为 `SummarizationNode` 会跨 KB Chat 图结构，本点采用方案 B：保留现有 `ConversationSummaryService`，但把默认值、keep、trim 统一到 settings。

## 第三个点 P0-3 验证

- RED：`uv run pytest tests/test_summary_settings.py` 起初 3 个失败，分别对应摘要默认值、General Chat keep/trim 参数、ConversationSummaryService trim helper 缺失。
- GREEN：`uv run pytest tests/test_summary_settings.py tests/test_general_chat_context_editing.py tests/test_context_budget_settings.py` 最终 `10 passed`。

## 第四个点 P0-4 代码取证

- `backend/src/app/services/context_builder.py`
  - `build_retrieval_context()` 原先计算所有结果 token，但循环无条件 `included.append(r)`，没有消费 `context_retrieval_max_tokens`。
  - `_chunk_tokens()` 基于 `_result_text()` 使用 `count_tokens_approximately()`。
  - `_truncate_text()` 是现有通用截断 helper，字符预算按 `token * 4` 近似。
- `backend/src/app/services/retrieval_service_contracts.py`
  - `RetrievalResult` 是 dataclass，包含 `chunk`、`score`、`context_text`。
  - `RetrievedChunk` 可在测试中直接构造，无需数据库或 Milvus。
- `backend/src/app/agents/tools/kb_retrieve.py`
  - 传入 `ContextBuilder` 时会调用 `build_retrieval_context(results)`，若 `truncation.truncated` 为真会追加“输出已截断”提示。

## 第四个点 P0-4 外部调研

- LangChain 官方 RAG 示例通常直接拼接 retrieved docs；官方 context engineering / LangGraph memory 文档强调 LLM 有固定 context window，需要显式 token 计数与裁剪。
- 本点为业务特化 RAG evidence budget，无现成 middleware；实现策略按当前结果排序顺序累加，超预算后丢弃后续低优先级结果。

## 第四个点 P0-4 验证

- RED：`uv run pytest tests/test_retrieval_context_budget.py` 起初 2 个失败，当前实现全量保留检索结果。
- GREEN：`uv run pytest tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 最终 `12 passed`。

## 第五个点 P0-5 代码取证

- `backend/src/app/agents/kb_chat_agentic/reflection_draft_generation.py`
  - `generate_draft()` 在结构化草稿失败后有 plain fallback，原先 `chat_model.bind(max_tokens=1024)`。
  - 同一函数会调用 `_attempt_local_plain_text_draft_repair()` 做本地覆盖缺口修复，调用点已有 `settings`，可最小透传。
- `backend/src/app/agents/kb_chat_agentic/reflection_draft_utils.py`
  - `_attempt_local_plain_text_draft_repair()` 原签名没有 `settings`，原先 `chat_model.bind(max_tokens=1024)`。
- `backend/src/app/agents/kb_chat_agentic/answer_subgraph_finalize.py`
  - `_answer_repair()` 原先 `chat_model.bind(max_tokens=1024)`，函数已持有 `settings`。
- `backend/src/app/agents/kb_chat_agentic/preprocess_plan_execution.py`
  - `_complexity_level_for_strategy()` 将 `direct -> simple`、`multi_query -> moderate`、`decomposition -> complex`。
  - `preprocess.py` 的 `query_plan()` 会写入 `complexity_level`，draft 预算可复用该状态字段。

## 第五个点 P0-5 外部调研

- LangChain Reference `Runnable.bind` 说明 bind 会把额外 kwargs 绑定到 Runnable，适合保留现有 `.bind(max_tokens=...)` 形态。
- LangChain OpenAI Reference `ChatOpenAI.max_tokens` 说明 `max_tokens` 是“Maximum number of tokens to generate”，并映射到 `max_completion_tokens` alias。
- 本地 introspection 确认当前安装版本：
  - `Runnable.bind(self, **kwargs: Any)`
  - `ChatOpenAI.model_fields["max_tokens"]` 的 alias 为 `max_completion_tokens`

## 第五个点 P0-5 验证

- RED：`uv run pytest tests/test_kb_chat_output_token_settings.py` 起初因缺少 `app.agents.kb_chat_agentic.output_token_budget` 失败；补充正数约束测试后也先观察到 `Settings(...=0)` 未报错。
- GREEN：`uv run pytest tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 最终 `18 passed`。

## 第六个点 P0-6 代码取证

- `backend/src/app/services/research_runtime_factory.py`
  - Deep Research 使用 `create_deep_agent(..., middleware=[build_breadth_gate_middleware(...)])`，适合直接扩展官方 agent middleware。
  - `ResearchRuntimeConfig` 的 `primary_model/subagent_model/finalizer_model` 都由 `build_deep_research_runtime_runner()` 创建，subagents 由 `create_deep_agent` 管理。
- `backend/src/app/agents/kb_chat_graph.py` / `kb_chat_agentic_graph.py`
  - KB Chat 当前是自建 `StateGraph`，不是 `create_agent`，不存在 agent middleware 参数。
  - LLM 调用分散在 `retrieval_subgraph.py`、`reflection_draft_generation.py`、`reflection_draft_utils.py`、`answer_subgraph_*` 中，均通过同一个 `chat_model` 实例传入。
  - 因此 LangChain `ModelCallLimitMiddleware` / `ModelFallbackMiddleware` 不能自动覆盖 KB Chat，必须使用薄 wrapper 或后续重构为 agent middleware 架构。
- `backend/src/app/integrations/model_runtime_config.py`
  - 当前运行时模型配置按 provider 与模型列表组织，`active_model` 只保证在 active provider 的 `models` 中。
  - fallback model 若只写模型名可能跨 provider 歧义，因此本点收敛为 `provider:model` 格式。

## 第六个点 P0-6 外部调研

- LangChain 官方 prebuilt middleware 文档说明 `ModelCallLimitMiddleware` 通过 `create_agent(..., middleware=[...])` 控制 thread/run 模型调用次数，thread limit 需要 checkpointer；`ModelFallbackMiddleware` 在主模型失败后按顺序尝试 fallback 模型。
- Deep Agents 官方 customization / reference 文档说明 `create_deep_agent` 支持额外 middleware，并在默认 middleware 栈之后应用。
- 本地 introspection 确认当前安装版本：
  - `ModelCallLimitMiddleware(thread_limit=None, run_limit=None, exit_behavior="end")`
  - `ModelFallbackMiddleware(first_model, *additional_models)`
  - `create_deep_agent(..., middleware: Sequence[AgentMiddleware] = (), ...)`

## 第六个点 P0-6 验证

- RED：`uv run pytest tests/test_agent_model_safety.py` 起初因缺少 `app.agents.kb_chat_agentic.model_guard` 失败；后续新增 provider-qualified fallback 测试先观察到未拒绝裸模型名。
- GREEN：`uv run pytest tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 最终 `23 passed`。

## 第七个点 P1-1 代码取证

- `backend/src/app/agents/retrieval_subgraph.py`
  - `_compress_context()` 当前先让 LLM 输出 `keep_all/subset/no_evidence`，随后只用 `candidate_context > input_tokens` 判断是否拒绝压缩。
  - 现状没有绝对 `context_retrieval_max_tokens` 上限，因此 `keep_all` 和 oversized subset 都可能把超预算 `final_context` 原样带入后续 draft/review。
  - 当前 `compressed_evidence_items` 保留的是 canonicalized evidence 顺序，天然可作为 rank-prune 输入。
- `backend/src/app/services/kb_evidence.py`
  - `build_evidence_context()` 的 token 计数包含 `[Sx]` 标签与换行开销，因此 budget prune 不能只按 excerpt token 估算。
  - `canonicalize_evidence_items()` / `build_citation_catalog()` 已足够支撑 budget prune 后的 catalog 重建。
- `backend/src/app/agents/kb_chat_agentic/schemas.py`
  - `ContextCompressDecision` 当前只有 `decision` 与 `items`；本点先把 `trimming_mode` 写入 `compression_stats`，不扩大到 schema 变更。

## 第七个点 P1-1 外部调研

- LangChain 官方 context engineering / `trim_messages` 文档强调需要显式 token 计数与硬预算裁剪，但没有针对 RAG evidence compression 的现成 middleware。
- 因此 `context_compress` 的预算硬顶仍需业务侧自建薄适配：在 LLM 选择后按当前 evidence 顺序做 token-based prune。

## 第七个点 P1-1 验证

- RED：`uv run pytest tests/test_retrieval_context_compress_budget.py` 起初 2 个失败，说明 `keep_all` 和 oversized subset 都没有触发 `budget_cap_enforced`。
- GREEN：`uv run pytest tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 最终 `25 passed`。

## 第八个点 P1-2 代码取证

- `backend/src/app/agents/retrieval_subgraph.py`
  - `_budget_by_complexity()` 当前只返回三项：`per_query_top_k / global_candidates_limit / rerank_input_limit`。
  - `_fallback_retrieval_budget()` 只构造这三项预算，并把 `complexity/query_count/upstream_retry_signal/retry_count` 写入 diagnostics。
  - `_merge_retrieval_plan_summary()` 会把 `budget` 原样铺到 `stage_summaries["retrieval_plan"]`，因此新增预算字段只要进入 `budget` 字典，就会自然进入 summary。
  - `_retrieval_plan_node()` 与 `_retrieval_budget_plan()` 都直接返回 `{"retrieval_budget": budget}`；新增字段会被整包写入 state。
- `backend/src/app/agents/kb_chat_agentic/reflection_retrieval.py`
  - `_resolve_retrieval_budget_payload()` 当前只解析并返回前三项预算，后续 `_invoke_kb_retrieve()` 也只把这三项放进 `kb_retrieve` payload。
  - 因此本点若只新增 `final_evidence_token_budget`，它会随 `state.retrieval_budget` 保存在图状态与分支状态中，但不会被检索执行层消费。
- `backend/src/app/agents/kb_chat_agentic/dispatch_fuse.py`
  - `make_send_task()` 会把整个 `retrieval_budget` dict 透传到扇出分支；新增字段不需要额外加线。
  - `build_retrieval_payload()` 只接受前三项预算，不接受 evidence token budget。
- `backend/src/app/agents/kb_chat_agentic/schemas.py`
  - `RetrievalPlanDecision` 当前结构化 schema 只有前三项预算和 `reasoning`；`extra="forbid"`，意味着 prompt / payload 若输出新字段，不同步改 schema 就会直接判 invalid。
- `backend/src/app/services/query_rewrite_retrieval_plan.py`
  - `plan_retrieval_budget()` 向 prompt 传入三项 fallback 预算，并在 structured success 后对前三项做 clamp。
  - `RetrievalPlanResult.meta` 当前只透出 `decision_source/fallback_reason/fallback_used/reasoning/query_count`；budget 本身通过 `result.budget` 返回，不在 meta 重复。
- `backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml`
  - 当前 JSON 合同、变量列表和 few-shot 都只覆盖前三项预算；若要让 LLM 返回新字段，模板与示例必须同步扩展。
- Trace / 展示层
  - `kb_chat_trace_display_shared.py` / `kb_chat_trace_display_output.py` 当前 retrieval_plan 节点展示只读 `query_count` 和 `per_query_top_k`，没有展示 token budget；本点可以先只保证 summary 存档，不必额外扩 UI。

## 第八个点 P1-2 外部调研

- LangChain 官方 context engineering 文档强调要显式记录“传入了什么上下文、为什么传入”，并建议逐个增加预算化能力、监控 token usage；对消息摘要和工具上下文有现成 middleware，但没有给 RAG evidence budget 提供通用 middleware。
- LangChain 官方 deep agents context engineering 文档说明长结果管理依赖 offloading、summarization 与 context isolation；大体原则仍是“超大上下文要外置或裁剪，只把当前需要的内容留在活动上下文”。
- 结合当前代码，这意味着 `final_evidence_token_budget` 仍应由业务侧显式建模和透传，而不是等待框架自动处理。

## 第九个点 P1-3 代码取证

- `backend/src/app/agents/kb_chat_agentic/preprocess_context_nodes.py`
  - `merge_context()` 是 KB Chat agentic 路径中首个也是主要直接读取 `state["messages"]` 的节点。
  - 当前流程是：取 persisted summary -> `_recent_turns(messages, max_turns=6)` -> 可选 `_generate_summary_from_turns()` -> `build_context_seed_from_messages(...)` -> `_select_turns_for_merge(...)` -> 合并 memory / summary / question。
  - 因此若要引入 token-aware `trim_messages`，最自然落点是在 `merge_context()` 读取 `messages` 后、调用 `_recent_turns()` 与 `build_context_seed_from_messages()` 之前。
- `backend/src/app/agents/kb_chat_agentic/preprocess_query_bundle.py`
  - `_extract_user_input()` 在 `state.user_input` 为空时会回退读取 `messages` 中最后一条 `HumanMessage`；若 `merge_context()` 要覆写 `messages`，必须保证最后用户消息仍被保留。
- `backend/src/app/services/kb_chat_context_seed.py`
  - `build_context_seed_from_messages()` 目前只按 `max_turns` 截最后若干轮，没有 token 预算概念；因此 `trim_messages` 应在其之前执行，而不是替换其职责。
- `backend/src/app/agents/kb_chat_agentic/answer_subgraph_finalize.py` / `reflection_draft_generation.py`
  - 后续 answer 子图不再读取历史 `messages`；主要依赖 `final_context`、`draft_answer`、`answer_paragraphs` 等派生状态。
- 全局检索
  - `rg --fixed-strings 'state.get(\"messages\")'` 结果显示 KB Chat agentic 路径中稳定直接读取历史消息的就是 preprocess 入口与 `_extract_user_input()`；这允许本点把影响范围收敛在 preprocess。

## 第九个点 P1-3 外部调研

- LangChain 官方 memory / short-term memory 文档把 `trim_messages` 作为模型调用前的标准裁剪工具，强调要显式配置 `strategy`、`start_on`、`end_on`、`include_system` 来保证消息序列满足 provider 约束。
- 本地 introspection 确认当前安装版本签名：
  - `trim_messages(messages, *, max_tokens, token_counter, strategy='last', allow_partial=False, end_on=None, start_on=None, include_system=False, text_splitter=None)`
- 结合当前仓库的消息形态，`strategy=\"last\"` 是最贴合“保留最近对话”的选项；本点还需要在测试里验证最后一条 `HumanMessage` 不会被裁掉。
- 本地实验还确认了两个实现细节：
  - 直接把 `count_tokens_approximately` 函数对象传给 `trim_messages` 时，当前版本不会按预期执行多消息总预算裁剪；使用官方内置 `token_counter=\"approximate\"` 才能得到正确行为。
  - 若把 persisted summary 与普通对话消息一起送入 `trim_messages(include_system=True)`，在极小 budget 下可能只保住 `SystemMessage` 而丢掉最后用户问题；因此实现上应先分离 summary，再只对普通对话消息执行 trim。

## 第十个点 P1-4 代码取证

- `backend/src/app/agents/general_chat_agent.py`
  - General Chat 当前 middleware 栈已有 `SummarizationMiddleware`、`ContextEditingMiddleware` 和可选 `HumanInTheLoopMiddleware`，适合继续追加 `LLMToolSelectorMiddleware`。
  - `build_general_chat_agent()` 是 General Chat 所有执行路径共用的唯一 agent 构造器，因此 selector 接这里即可覆盖正常执行、streaming 与 resume。
- `backend/src/app/services/research_runtime_factory.py`
  - Deep Research 顶层 agent 通过 `create_deep_agent(..., middleware=[...])` 构造，当前已有 breadth gate 与 model safety middleware，天然适合继续追加 tool selector。
  - `build_research_tool_registry()` 生成的工具集中包含 `record_runtime_activity`，这是 runtime live-board 所需关键工具；若接入 selector，必须保证它被 `always_include` 保留。
- `backend/src/app/agents/tool_calling/registry.py`
  - 工具注册层已经统一提供 `tool_meta_by_name` 与 `tool_groups`，但本点不需要改 registry，只需要消费最终 `tools` 列表长度与关键工具名。
- `backend/src/app/core/settings.py`
  - 当前没有任何 tool selector 配置，适合新增一组独立 settings，并复用现有 `parse_string_list` + `field_validator` 解析 `always_include`。

## 第十个点 P1-4 外部调研

- LangChain 官方 `LLMToolSelectorMiddleware` 文档与本地源码说明：
  - middleware 在主模型调用前用一个 selection model 根据最后一条用户消息筛选工具。
  - 配置核心只有 `model`、`max_tools`、`always_include`，其中 `always_include` 不计入 `max_tools`。
  - 若 `model` 为空，则默认复用主模型；若工具数量不多，则可以直接跳过 selector。
- 本地源码 introspection 进一步确认：
  - `LLMToolSelectorMiddleware(*, model: str | BaseChatModel | None = None, system_prompt: str = ..., max_tools: int | None = None, always_include: list[str] | None = None)`
  - middleware 只处理 `BaseTool` 列表和 provider-specific tool dict，不会自动理解本仓库的 MCP 审批语义；因此 MCP HITL 边界仍应保持在 `HumanInTheLoopMiddleware`。

## 第十一个点 P1-5 代码取证

- `backend/src/app/services/research_runtime_workspace.py`
  - `build_runtime_request_files_with_budget()` 当前先把 `priority_paths` 全量放入 `request_files`，随后会继续把剩余预算内的非 priority 文件也一并放入 `request_files`。
  - 这意味着当前 `files_budget_snapshot.spilled_paths` 只是“超预算未预置”列表，而不是严格的“按需加载”列表。
- `backend/src/app/services/deep_research_runtime.py`
  - `run_session()` 在构建 `workspace_files` 后，直接把 `_build_runtime_request_files(...)` 返回的 `request_files` 塞入 `request["files"]`。
  - runtime 本身不会再额外把“未进入 request_files 的 workspace_files”交给 backend；因此若继续使用 `StateBackend`，这些文件对 read/grep/glob 工具是不可见的。
- `backend/src/app/services/research_runtime_factory.py`
  - Deep Research runtime 当前把 `backend=build_research_backend(...)` 传给 `create_deep_agent()`。
  - `build_research_backend()` 返回 `CompositeBackend(default=StateBackend(), routes={"/memories/": StoreBackend(), "/skills/": StoreBackend()})`；默认 workspace/scratch 都落在 `StateBackend`。
- `backend/src/app/config/runtime_contract.py`
  - `priority_layout_attrs` 目前覆盖 mission / plan / claim_map / evidence_ledger / claim_bundles / section_briefs / report_context / task_graph；再加上 request context 4 个文件与 guide，共同组成 `priority_paths`。
  - runtime 本地文档注入 `RESEARCH_RUNTIME_WORKSPACE_CONTEXT_DOCS` 也走 `workspace_files` 路径。

## 第十一个点 P1-5 外部调研

- Deep Agents 本地包源码 `deepagents/graph.py` 已确认：
  - `create_deep_agent()` 默认 middleware 栈中已包含 `FilesystemMiddleware`，内置 `ls/read_file/write_file/edit_file/glob/grep` 工具。
  - 因此当前仓库并不缺“文件搜索工具”，真正问题是 backend 中是否存在相应文件。
- Deep Agents 本地包源码 `deepagents/backends/state.py` 已确认：
  - `StateBackend` 明确写明“要预置文件，必须在 invoke 时传 `files`”；未进入状态的文件不会被 `read/grep/glob` 或 `download_files` 看到。
  - `StateBackend.upload_files()` 目前 `NotImplemented`，不能靠预热上传把大量文件批量塞进状态。
- Deep Agents 本地包源码 `deepagents/backends/composite.py` / `store.py` 已确认：
  - `CompositeBackend.download_files()/upload_files()` 支持按路由批量下载/上传。
  - `StoreBackend.upload_files()` 可真实持久化 `/skills/`、`/memories/` 这类路由文件。
- 结论：
  - 方案里“再加一层 `FilesystemFileSearchMiddleware`”并不能解决 `StateBackend` 对未预置文件不可见的问题。
  - 若要实现真正的“priority preload + 其余 on-demand”，需要为 Deep Research 增加一层 seed/fallback backend，让未预置文件仍能被 filesystem 工具与 `SkillsMiddleware` / `MemoryMiddleware` 读取。

## 第十二个点 P1-6 代码取证

- `backend/src/app/services/research_runtime_types.py`
  - `ResearchLargeResultPolicy.max_inline_chars` 当前硬编码为 `6_000`，并通过 `DEFAULT_RESEARCH_LARGE_RESULT_POLICY` 成为 `ResearchRuntimeConfig.large_result_policy` 的默认值。
  - 当前没有 `priority_inline_chars`，也没有 settings -> policy 的工厂函数。
- `backend/src/app/services/deep_research_runtime.py`
  - `build_deep_research_runtime_runner()` 构造 `ResearchRuntimeConfig` 时只传模型、system prompt 与 memory paths，没有从 `Settings` 注入 `large_result_policy`。
- `backend/src/app/services/research_runtime_workspace.py`
  - `_build_bootstrap_workspace_file_entries()` 只用 `large_result_policy.max_inline_chars` 判断 artifact 是否 inline；超过阈值时调用 `spill_json_payload()` 写入 `/scratch/research-spill/<session>/...`。
  - `build_session_bootstrap_workspace_files()` 只负责把 session artifacts 转为 workspace 文件，P1-5 后这些文件会进入 seed registry；本点只改 inline/spill 判定，不改 on-demand backend。
- `backend/src/app/config/runtime_contract.py`
  - `RESEARCH_RUNTIME_LAYOUT_MANIFEST.bootstrap_artifact_key_to_attr` 可把 artifact_key 映射到 layout 路径属性。
  - `priority_layout_attrs` 当前定义 priority 路径集合，适合用来判定哪些 bootstrap artifact 可使用更高的 `priority_inline_chars`。
- `backend/src/app/core/settings.py`
  - Deep Research 相关字段已经集中在 `deep_research_thread_model_call_limit` / `deep_research_run_model_call_limit` / `deep_research_fallback_model_id` 附近，新增字段应保持同一区域和 `Field(..., ge=1, alias=...)` 风格。

## 第十二个点 P1-6 外部调研

- LangChain / Deep Agents 官方文档说明 Deep Agents 通过 filesystem/backend 管理 agent 文件状态，长任务应把可按需读取的内容放入文件系统而不是全部塞进活动 prompt。
- LangChain context engineering 文档强调通过 summarization、trimming、selective retrieval 与 offloading 管理有限上下文窗口；本点对应的是 Deep Research bootstrap artifact 的 offloading 阈值参数化。
- Anthropic prompt caching / long context 文档强调长上下文输入会带来成本和延迟，需要对稳定大块内容做缓存或减少反复注入；本点先完成阈值收紧与 settings 注入，不提前做 P1-7 Prompt Caching。
- 结论：
  - P1-6 的最小实现是新增 `DEEP_RESEARCH_LARGE_RESULT_MAX_INLINE_CHARS=2000` 与 `DEEP_RESEARCH_PRIORITY_INLINE_CHARS=12000`，由 `ResearchLargeResultPolicy.from_settings()` 注入 runtime。
  - bootstrap artifact 的普通 inline 阈值收紧到 2,000 字符，priority artifact 允许 12,000 字符；超过阈值仍走既有 spill 文件路径。

## 第十三个点 P1-7 代码取证

- `backend/pyproject.toml`
  - 当前已经依赖 `langchain-anthropic>=1.4.0,<2`，无需新增依赖。
- 本地包 `langchain_anthropic.middleware.AnthropicPromptCachingMiddleware`

## 第十五个点 P2-3 代码取证与外部调研

- 当前方案原文把 `P2-3` 表述为“接入 Anthropic Context Management API”，但用户新增约束明确要求：`不能只是针对Claude模型的memory，要是通用的memory`。
- 这意味着本点的第一步不是直接写 Anthropic-only 代码，而是先确认系统主 memory 抽象是否必须 provider-agnostic；结论是必须。

### 本地代码取证

- `backend/src/app/agents/general_chat_agent.py`
  - General Chat 通过 `create_agent(...)` 统一装配 middleware，目前已有：
    - `SummarizationMiddleware`
    - `ContextEditingMiddleware`
    - `LLMToolSelectorMiddleware`
    - `AnthropicPromptCachingMiddleware`
    - `HumanInTheLoopMiddleware`
  - 当前没有任何 provider-agnostic 长期 memory 适配层；如果后续要给 General Chat 接长期记忆，这是最自然的统一入口。
- `backend/src/app/services/research_runtime_factory.py`
  - Deep Research 顶层 runtime 通过 `create_deep_agent(...)` 构造，当前显式传入：
    - `middleware=[breadth gate, tool selector, anthropic prompt caching, model safety]`
    - `memory=list(config.memory_paths)`
    - `backend=build_research_backend(...)`
    - `store=store`
  - 这里的 `memory_paths` 明显更接近 deepagents 的文件/目录型 memory，而不是 LangMem 这种结构化长期事实存储。
  - 因此 Deep Research 若要继续扩展长期记忆，应该区分两层：
    - runtime 文件/工作区 memory：保留现有 `memory_paths`
    - provider-agnostic 长期事实 memory：另接 `langmem + BaseStore`
- `backend/src/app/agents/kb_chat_memory.py`
  - 当前磁盘内容已不是旧的“最近 5 条 Q/A 列表”，而是 P2-1 新实现：
    - `KbChatFact`
    - `create_memory_store_manager(...)`
    - `create_search_memory_tool(...)`
    - `ReflectionExecutor(...)`
    - namespace 模板 `("kb_chat", "{user_id}", "{kb_scope}")`
  - 说明仓库里已经有一条真实可用的 provider-agnostic memory 主路径，不应在 P2-3 再退回 Claude-only memory middleware。
- `backend/src/app/core/settings.py`
  - 现有 memory 相关配置已包含：
    - `MEMORY_ENABLED`
    - `MEMORY_STORE_BACKEND`
    - `MEMORY_STORE_URL`
    - `MEMORY_STORE_PATH`
    - `KB_CHAT_MEMORY_MODEL_ID`
    - `KB_CHAT_MEMORY_SEARCH_LIMIT`
    - `KB_CHAT_MEMORY_MAX_STEPS`
    - `KB_CHAT_MEMORY_REFLECTION_DELAY_SECONDS`
  - 这些配置已足够支撑“继续沿用 provider-agnostic memory 主层”的方向。
- `backend/tests/test_kb_chat_langmem_memory.py`
  - 已覆盖 KB Chat 的 LangMem 写入、search namespace、preprocess 读取、delayed reflection。
- `backend/tests/test_tool_selector_middleware.py`
  - 已确认 General Chat / Deep Research 当前的统一 middleware 扩展点都真实存在并已覆盖。

### 本地已安装包取证

- 在 `backend` 目录执行本地 introspection，确认：
  - `langchain-anthropic==1.4.0`
  - `anthropic==0.86.0`
- `ChatAnthropic.model_fields` 当前确实包含：
  - `betas`
  - `mcp_servers`
  - `context_management`
  - `reuse_last_container`
- `langchain_anthropic.middleware` 当前确实存在：
  - `StateClaudeMemoryMiddleware`
  - `FilesystemClaudeMemoryMiddleware`
- 但本地源码同样明确写明这两个 middleware 的语义：
  - `StateClaudeMemoryMiddleware`: “Provides Anthropic's memory tool using LangGraph state for storage”
  - `FilesystemClaudeMemoryMiddleware`: “Provides Anthropic's memory tool using local filesystem for storage”
  - 二者都会注入 Anthropic 推荐的 memory system prompt，并默认把路径限制在 `/memories`
- 结论：
  - 它们是 Claude provider 下的 memory tool 接法。
  - 它们不是仓库统一 memory 抽象，不能替代 `langmem + BaseStore` 作为系统主 memory 层。

### 外部官方资料调研结论

- LangGraph / LangMem 官方能力线：
  - `langmem.create_memory_store_manager`
  - `langmem.create_search_memory_tool`
  - `langmem.ReflectionExecutor`
  - `langgraph.store.base.BaseStore`
  - 这条链路天然是 provider-agnostic，适合作为系统统一长期记忆主层。
- Anthropic 官方 context editing / context management 文档：
  - 重点是 Claude API 端的上下文管理能力与 provider-specific tool 协议。
  - 这些能力适合做 Anthropic provider 下的可选增强，例如更积极地清理上下文或复用 Claude 原生工具协议。
  - 但它们并不替代应用层对长期记忆 schema、namespace、store、检索和抽取流程的控制。

### 本点设计纠偏结论

- `P2-3` 不应被实现成“把 Claude memory middleware 接到系统主路径上”。
- 正确方向应是：
  - 系统主 memory：`langmem + langgraph BaseStore`
  - Anthropic `context_management` / Claude memory tool：仅作 Anthropic provider 的 optional enhancement
- 对三条主链路的建议落点：
  - General Chat：
    - 如要补长期记忆，应新增 provider-agnostic memory adapter，底层复用 `langmem`
    - Anthropic provider 下可额外透传 `context_management`
  - Deep Research：
    - 继续把 `memory_paths` 视为 runtime 文件/工作区 memory
    - 若补长期事实记忆，也应另接 `langmem + store`
    - 不要拿 Claude memory middleware 取代 `memory_paths` 或仓库统一 memory 抽象
  - KB Chat：
    - 保持 P2-1 的 LangMem 方案，不再叠加 Claude-only memory middleware

### 若继续编码，最可能的最小实现边界

- 新增一个 provider-aware 但 provider-agnostic 主层的 memory 装配模块，例如：
  - `backend/src/app/agents/provider_memory.py`
  - 职责：
    - 统一创建 LangMem manager / search tool / namespace config
    - 针对 Anthropic provider 可选生成 `context_management` 配置或附加 middleware
    - 对非 Anthropic provider 返回 no-op / 仅 LangMem 路径
- 最可能受影响的文件：
  - `backend/src/app/agents/general_chat_agent.py`
  - `backend/src/app/services/research_runtime_factory.py`
  - `backend/src/app/integrations/chat_model_factory.py`
  - `backend/src/app/core/settings.py`
  - 对应测试文件
- 若要严格遵守“一次只做一个点”，下一次编码前应先把 `P2-3` 的实施目标收敛成以下二选一之一：
  - 选项 A：只做 Anthropic `context_management` 的 provider-aware 可选透传，不触碰系统主 memory
  - 选项 B：把方案文档中的 `P2-3` 纠偏为“provider-aware context management 可选增强”，然后编码实现对应薄适配层

## 第十六个点 P2-4 代码取证与外部调研

### 当前代码取证

- `backend/src/app/services/context_builder.py`
  - `build_metrics()` 现在只返回三层结构：
    - `budgets`
    - `usage`
    - `truncation`
  - 当前没有派生指标层，例如：
    - `context_utilization`
    - `truncation_rate`
    - `compression_ratio`
  - 但其已有数据足以推导其中一部分：
    - `usage.summary/history/retrieval/tools/total`
    - `budgets.llm_input_tokens/history_tokens/retrieval_tokens/tool_tokens/summary_tokens`
    - `truncation.summary/history/retrieval/tools`
- `backend/src/app/services/general_chat_service_runtime.py`
  - `_build_context_metrics()` 目前把消息总 token / chars / messages 汇总成 `history_usage` 后直接调用 `ContextBuilder.build_metrics()`。
  - 这意味着只要 `build_metrics()` 增强，General Chat 会自动获得新上下文指标，无需额外改 agent 调用链。
- `backend/src/app/services/kb_chat_service_observability.py`
  - `_build_observability()` 会把 `ContextBuilder.build_metrics()` 的结果挂到 `metrics["context"]`。
  - 当前 retrieval 相关 usage / truncation 已真实接入，因此 `context_utilization` 与 `truncation_rate` 在 KB Chat 路径上是可落地的。
- `backend/src/app/agents/kb_chat_agentic/preprocess_context_nodes.py`
  - `merge_context()` 当前已经在 stage summary 中记录：
    - `compression_ratio`
    - `memory_included`
    - `turns_seen`
    - `turns_selected`
  - 但还没有记录 memory search 返回数、去重后保留数、最终渲染数，因此 `memory_recall_precision` 目前没有真实分母/分子基础。
  - 本点若要最小化实现该指标，应优先在 `merge_context` 阶段补充：
    - search 返回条数
    - 过滤后条数
    - 实际渲染条数
- `backend/src/app/agents/kb_chat_memory.py`
  - `aget_kb_chat_memory()` 目前只返回整合后的 `entries`，没有直接暴露搜索原始命中数之外的派生指标。
  - 但 `merge_context()` 已经拿到 `memory_data["entries"]`，因此本点不需要改 memory store 层，只需在 merge 阶段统计即可。
- `backend/src/app/services/research_observability.py`
  - Deep Research 已有独立 gate / metrics 体系，但这条链路与 `ContextBuilder` 没有现成汇合点。
  - 如果本点把 P2-4 扩到 Deep Research，会立刻进入跨体系改造；不符合“单点最小改动”。

### 现有测试与最适合复用的入口

- `backend/tests/test_context_budget_settings.py`
  - 已覆盖 `ContextBuilder.build_metrics()` 暴露 budgets 的基础行为。
  - 最适合作为本点 RED/GREEN 的主测试文件，追加对派生指标的断言。
- `backend/tests/test_kb_chat_langmem_memory.py`
  - 已覆盖 `merge_context()` 读取 memory 后写入 `stage_summaries["merge_context"]` 的行为。
  - 适合扩展为 memory 指标断言入口。
- 当前仓库尚未发现现成 LangSmith tracing 测试或本地 wrapper。
  - 说明本点若引入 LangSmith 真实集成，会缺乏近邻模式和验证路径，不适合最小实现。

### 外部调研结论

- LangSmith 官方文档支持在 tracing/runs 上追加 metadata / tags，但这属于“把本地已计算指标上报到观测后端”的第二层工作。
- 当前仓库虽然依赖中已包含 `langsmith`，但源码里没有实际接入路径。
- 因此 `P2-4` 最合理的最小实现顺序是：
  1. 先在本地 `metrics` / `stage_summaries` 中把指标真实算出来。
  2. 后续若用户单独要求，再做 LangSmith metadata / tracing 对接。

### 本点最小实现边界

- 本点做：
  - `ContextBuilder.build_metrics()` 新增可由当前数据真实推导的派生指标：
    - `context_utilization`
    - `truncation_rate`
    - `overall_truncated`
  - `merge_context()` 新增 memory 相关基础指标：
    - `memory_candidates`
    - `memory_retained`
    - `memory_rendered`
    - `memory_recall_precision`
- 本点不做：
  - LangSmith 远端集成
  - Grafana / 日志面板
  - `tool_selection_drop_rate`，因为当前 `LLMToolSelectorMiddleware` 无仓库内埋点
  - `prompt_cache_hit_rate`，因为当前仓库没有稳定消费 Anthropic usage metadata 的代码路径
  - Deep Research 独立 observability 体系扩改
  - 当前签名为 `AnthropicPromptCachingMiddleware(type="ephemeral", ttl="5m", min_messages_to_cache=0, unsupported_model_behavior="warn")`。
  - middleware 会对 Anthropic 模型的 system message、tool definitions 和最后 cacheable block 添加 `cache_control`；非 Anthropic 模型可通过 `unsupported_model_behavior="ignore"` 静默跳过。
- `backend/src/app/agents/general_chat_agent.py`
  - General Chat 通过 `create_agent(..., middleware=middleware)` 构造，已有 Summarization、ContextEditing、LLMToolSelector 和 HITL middleware，适合直接追加官方 Anthropic prompt caching middleware。
  - 生产调用点共有 normal/recovery/stream/resume-stream/resume 五处，必须透传 settings，否则关闭开关与 TTL 覆盖不会生效。
- `backend/src/app/services/research_runtime_factory.py`
  - Deep Research 顶层 agent 通过 `create_deep_agent(..., middleware=middleware)` 构造，适合直接追加官方 middleware。
  - middleware 顺序应在 tool selector 之后、model safety 之前，让缓存标记作用于筛选后的 tools 和最终 system prompt，同时保留 call limit/fallback 保护。
- KB Chat 边界：
  - KB Chat 是自建 LangGraph，多个节点直接调用 `chat_model.ainvoke()` 或结构化模型；agent middleware 不能直接覆盖这些调用。
  - 在本点为 KB Chat 做完整 prompt caching 需要包装 `bind()`、`with_structured_output()` 与多处直接调用，风险和范围明显大于 P1-7 的“10 行 middleware”目标，因此本点不改 KB Chat。

## 第十三个点 P1-7 外部调研

- LangChain Anthropic 官方文档提供 `AnthropicPromptCachingMiddleware`，示例为 `from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware` 后加入 `create_agent(..., middleware=[...])`。
- Anthropic 官方 prompt caching 文档说明通过 `cache_control={"type":"ephemeral"}` 标记可缓存内容，适合 system prompt、tool definitions 与长文档上下文。
- 结论：
  - 本点采用官方 `AnthropicPromptCachingMiddleware`，不自建 `wrap_model_call`。
  - 新增 `ANTHROPIC_PROMPT_CACHING_ENABLED=true`、`ANTHROPIC_PROMPT_CACHE_TTL=5m`、`ANTHROPIC_PROMPT_CACHE_MIN_MESSAGES=0`；非 Anthropic 模型行为设置为 `ignore`，避免默认开启时影响 OpenAI/Ollama/NVIDIA。

## 第十四个点 P2-1 代码取证

- `backend/src/app/agents/kb_chat_memory.py` 当前是自建 LangGraph Store 适配：`kb_chat_user_namespace()` 生成 `("kb_chat", "user", uid, kb_scope)`，`kb_chat_thread_key()` 生成 `kb_chat_memory:<thread>`，`append_kb_chat_memory_entry()` 读旧 payload 后追加有界 `entries` 列表并按 TTL 写回。
- `backend/src/app/agents/kb_chat_agentic/preprocess_context_nodes.py` 在 `merge_context()` 中读取 `runtime.store`，按 runtime context / `memory_keys` 解析 `thread_id/user_id/kb_ids`，调用 `aget_kb_chat_memory()` 和 `render_kb_chat_memory_snippet()` 后参与 summary/memory conflict resolution。
- `backend/src/app/services/kb_chat_service_finalize.py` 在成功状态且 `settings.memory_enabled` 时调用 `append_kb_chat_memory_entry(StoreManager.get_store(), ...)`，属于最佳努力写入，异常只记录 warning。
- `backend/src/app/core/memory_store.py` 已使用 `langgraph.store.postgres.AsyncPostgresStore` / `InMemoryStore`，因此 P2-1 不需要新增 store 后端，只需要替换 KB Chat 的自建 payload 逻辑。

## 第十四个点 P2-1 外部调研

- LangMem 官方文档建议用 `create_memory_store_manager(model, namespace=(...), schemas=[...], store=...)` 管理长期记忆，用 `create_manage_memory_tool` / `create_search_memory_tool` 在 agent 工具链中暴露记忆读写。
- 本地 `langmem` 签名确认：`create_memory_store_manager(model, *, schemas=None, instructions=..., enable_inserts=True, enable_deletes=False, query_limit=5, namespace=(...), store=None, phases=None)` 返回 `MemoryStoreManager`。该 manager 支持 `asearch(...)`、`aput(...)`、`ainvoke({"messages": ...}, config=...)` 和 `get_namespace(config)`。
- 本地 `ReflectionExecutor(manager, store=...)` 支持 `submit(payload, config=..., after_seconds=..., thread_id=...)`，后台 worker 会用 manager 同步 `invoke()` 写入 store；若不给 `store` 则需要 LangGraph runtime store。
- 结论：当前 KB Chat 是 LangGraph 状态图而非 ReAct agent，直接把 `create_manage_memory_tool/search_memory_tool` 挂入工具列表不会被图节点自动调用；本点应以 LangMem manager/executor/search 迁移持久化形态，并保留现有 preprocess/finalize 边界。
