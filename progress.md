# Progress

## 2026-04-20

### Session Start

- 已确认本轮使用 `development-orchestration`，并按要求建立文件式控制面。
- 已将 `F:\毕设\code\上下文优化方案.md` 作为当前已批准规格。
- 已记录当前工作树存在用户改动，后续提交将避免包含无关文件。

### Current Status

- 当前状态：`已验证通过`
- 已确认第一个点的最小边界：
  - 主改动：`backend/src/app/core/settings.py`
  - 直接消费方：`backend/src/app/integrations/langchain_profiles.py`
  - 最小预算透传：`backend/src/app/services/context_builder.py`
- 已完成：
  - 新增 `backend/tests/test_context_budget_settings.py`，先跑出 2 个失败用例，再修改生产代码。
  - 定向测试 `uv run pytest tests/test_context_budget_settings.py` 最终 `4 passed`。
  - 按仓库规则重建 backend graphify 图谱。
  - 完成本地 diff 审查，未发现需要在本点继续扩大的 correctness 问题。
- 已提交：
  - `01c6705 feat(context): enable default token budgets`
- 稳定检查点：
  - `P0-1` 已完成并单独提交。
  - 当前工作树剩余变化仅包含用户已有改动与本地 planning files，未混入第二个点的代码修改。
  - 下一步：进入 `P0-2`，先读工具上下文拼装链路并做官方文档调研，再决定 RED 测试入口。

### P0-2

- 当前状态：`已验证通过`
- 已完成：
  - 调研 General Chat 的全部 `build_general_chat_agent()` 调用点。
  - 查询 LangChain 官方文档并用本地 introspection 确认 `ContextEditingMiddleware` / `ClearToolUsesEdit` 签名。
  - 新增 `backend/tests/test_general_chat_context_editing.py`，先观察到构造器缺少 `tool_context_trigger_tokens` 的 RED 失败。
  - 在 General Chat middleware 中加入 `ContextEditingMiddleware`，并由 `settings.context_tool_max_tokens` 驱动 `ClearToolUsesEdit.trigger`。
  - 对 `None` 或非正数预算保留 LangChain 默认 `100_000` 触发阈值，避免显式关闭预算时构造失败。
  - 定向测试 `uv run pytest tests/test_general_chat_context_editing.py tests/test_context_budget_settings.py` 通过，结果 `6 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 下一步：只暂存 P0-2 相关源码/测试文件，创建单独 git 提交。
- 已提交：
  - `867dcaf feat(context): edit stale general chat tool results`

### P0-3

- 当前状态：`已验证通过`
- 已完成：
  - 取证 General Chat、ConversationSummaryService、KB Chat preprocess 的摘要链路。
  - 查询 LangChain 官方文档并用本地 introspection 确认 `SummarizationMiddleware` 支持 `trim_tokens_to_summarize`。
  - 新增 `backend/tests/test_summary_settings.py`，先观察到 3 个 RED 失败。
  - 将 `summary_enabled` 默认打开，`summary_trigger_min_tokens` 调整为 `2_000`，新增 `summary_keep_messages=20` 与 `summary_trim_tokens=4_000`。
  - General Chat 的 `SummarizationMiddleware` 改为使用 settings 驱动 `keep` 和 `trim_tokens_to_summarize`。
  - `ConversationSummaryService` 与 KB Chat preprocess 共享 `resolve_summary_trim_tokens()`。
  - 定向测试 `uv run pytest tests/test_summary_settings.py tests/test_general_chat_context_editing.py tests/test_context_budget_settings.py` 通过，结果 `10 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 下一步：只暂存 P0-3 相关源码/测试文件，创建单独 git 提交。
- 已提交：
  - `e0d84d0 feat(context): align summary budget settings`

### P0-4

- 当前状态：`已验证通过`
- 已完成：
  - 取证 `ContextBuilder.build_retrieval_context()`、`RetrievalResult` / `RetrievedChunk`、`kb_retrieve` 调用链。
  - 查询官方文档确认 RAG docs 拼接需要业务侧硬预算裁剪。
  - 新增 `backend/tests/test_retrieval_context_budget.py`，先观察到 2 个 RED 失败。
  - `build_retrieval_context()` 按结果顺序累加 token，超出 `context_retrieval_max_tokens` 后停止纳入后续结果。
  - 当预算小于 Top-1 时，保留 Top-1 并使用 `_truncate_text()` 截断到预算。
  - 修正 `_truncate_text()` 让省略号也计入字符预算，避免近似 token 超过硬预算。
  - 定向测试 `uv run pytest tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `12 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 下一步：只暂存 P0-4 相关源码/测试文件，创建单独 git 提交。

### P0-5

- 当前状态：`已验证通过`
- 已完成：
  - 取证 KB Chat 三处 `max_tokens=1024`：plain fallback、本地 plain-text draft repair、answer repair。
  - 查询 LangChain 官方/Reference 文档并用本地 introspection 确认保留 `.bind(max_tokens=...)` 是当前正确调用形态。
  - 新增 `backend/tests/test_kb_chat_output_token_settings.py`，先观察到缺少 resolver 模块和非正数 settings 未拒绝的 RED 失败。
  - 新增 `kb_chat_draft_max_tokens`、`kb_chat_repair_max_tokens`、`kb_chat_plain_fallback_max_tokens` 三项配置，并加 `ge=1` 约束。
  - 新增 `output_token_budget.py`，按 `simple/moderate/complex` 将 draft 基础预算扩展为 `1.0/1.25/1.5`，repair 与 plain fallback 使用独立配置。
  - `generate_draft()` 的结构化草稿与 retry 草稿使用复杂度 draft 预算，plain fallback 使用 fallback 预算。
  - `_attempt_local_plain_text_draft_repair()` 与 `_answer_repair()` 使用 repair 预算。
  - 定向和回归测试 `uv run pytest tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `18 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 下一步：只暂存 P0-5 相关源码/测试文件，创建单独 git 提交。

### P0-6

- 当前状态：`已验证通过`
- 已完成：
  - 取证确认 Deep Research 使用 `create_deep_agent`，可直接接 LangChain 官方 `ModelCallLimitMiddleware` / `ModelFallbackMiddleware`。
  - 取证确认 KB Chat 当前为自建 `StateGraph` + 直接 `chat_model` 调用，官方 agent middleware 无法自动覆盖，因此本点使用最小自建 wrapper 保持真实生效。
  - 查询官方文档并用本地 introspection 确认 `ModelCallLimitMiddleware`、`ModelFallbackMiddleware` 与 `create_deep_agent` 当前签名。
  - 新增 `backend/tests/test_agent_model_safety.py`，先观察到缺少 `model_guard` 模块与 fallback model 裸名称未拒绝的 RED 失败。
  - 新增 `model_safety.py` 统一装配 agent middleware；Deep Research runtime 接入 thread/run 限流与可选 fallback model。
  - 新增 `kb_chat_agentic/model_guard.py`，为 KB Chat 自建图统一包装 `chat_model`，实现 run 级模型调用上限、失败后 fallback 重试，以及 guard metadata 暴露。
  - `create_fallback_chat_model()` 收敛为 `provider:model` 格式，避免跨 provider 同名模型歧义。
  - 新增 settings：`KB_CHAT_RUN_MODEL_CALL_LIMIT`、`KB_CHAT_FALLBACK_MODEL_ID`、`DEEP_RESEARCH_THREAD_MODEL_CALL_LIMIT`、`DEEP_RESEARCH_RUN_MODEL_CALL_LIMIT`、`DEEP_RESEARCH_FALLBACK_MODEL_ID`。
  - 定向与回归测试 `uv run pytest tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `23 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 边界：
  - 本点没有把官方 middleware 强行声明为已覆盖 KB Chat 全部直接模型调用；KB Chat 仍是自建图上的薄 wrapper 方案。
  - General Chat 的 model fallback / call limit 仍留在方案后续阶段，不混入本次提交。
- 下一步：只暂存 P0-6 相关源码/测试文件，创建单独 git 提交。

### P1-1

- 当前状态：`已验证通过`
- 已完成：
  - 取证确认 `context_compress` 当前只在“压缩后 token 小于输入”时采纳，没有绝对 `context_retrieval_max_tokens` 上限。
  - 查询官方文档确认 RAG evidence compression 没有现成 middleware，可行方案是业务侧 budget prune。
  - 新增 `backend/tests/test_retrieval_context_compress_budget.py`，先观察到 `keep_all` 与 oversized subset 都未触发 `budget_cap_enforced` 的 RED 失败。
  - 在 `retrieval_subgraph.py` 新增 `_budget_prune_by_rank()`，按当前 evidence 顺序和真实 `build_evidence_context()` token 计数执行硬预算裁剪。
  - `_compress_context()` 在压缩结果仍超 `context_retrieval_max_tokens` 时统一触发 budget prune，并记录 `fallback_reason=\"budget_cap_enforced\"` 与 `trimming_mode`。
  - 定向与回归测试 `uv run pytest tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `25 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 下一步：只暂存 P1-1 相关源码/测试文件，创建单独 git 提交。
- 已提交：
  - `d78f9d1 feat(context): cap compressed retrieval context`

### P1-2

- 当前状态：`已验证通过`
- 已完成：
  - 重新读取 `上下文优化方案.md`、`backend/graphify-out/GRAPH_REPORT.md`、`retrieval_subgraph.py`、`reflection_retrieval.py`、`query_rewrite_retrieval_plan.py`、`query_rewrite_service.py`、`retrieval_plan.yaml`，确认 `retrieval_budget` 当前只稳定承载三项项数预算。
  - 用 `ace-tool` 与源码交叉取证：`retrieval_budget` 的后续执行消费面只在 `reflection_retrieval._resolve_retrieval_budget_payload()` 与 `kb_retrieve` 载荷构造中读取前三项；`context_compress` 当前只读 `settings.context_retrieval_max_tokens`，不读 `state.retrieval_budget`。
  - 查询 LangChain 官方 context engineering / retrieval / deep agents 文档，确认检索证据 token budget 没有现成 middleware，需要业务侧显式管理；这与方案要求的双轴预算一致。
- 追加完成：
  - 新增 `backend/tests/test_retrieval_plan_budget_settings.py`，先观察到 3 个 RED 失败，分别对应 fallback budget 缺字段、`RetrievalPlanDecision` 禁止新字段、planner 未透传 / clamp 新预算。
  - `retrieval_subgraph.py` 新增 `_default_final_evidence_token_budget()`，让 fallback budget 默认产出 `final_evidence_token_budget = context_retrieval_max_tokens * 0.9`。
  - `RetrievalPlanDecision`、`query_rewrite_retrieval_plan.py` 与 `retrieval_plan.yaml` 同步扩展第四个预算字段；planner 调用时透传 fallback token budget，并在服务端将 LLM 返回值 clamp 到 fallback 上限。
  - `stage_summaries["retrieval_plan"]` 与 `state.retrieval_budget` 已自然携带该字段；扇出分支透传依旧由 `make_send_task()` 复用整包 budget 完成，无需额外分支逻辑。
  - 定向测试 `uv run pytest tests/test_retrieval_plan_budget_settings.py` 通过，结果 `6 passed`。
  - 回归测试 `uv run pytest tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `31 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 当前边界：
  - 本点先补齐 `final_evidence_token_budget` 的生成、结构化规划、stage summary 与透传。
  - 不在本点把 retrieval/rerank 执行层改成直接消费 `final_evidence_token_budget`，也不重复实现 `P1-1` 的 compress hard cap。
- 下一步：只暂存 P1-2 相关源码/测试文件，创建单独 git 提交；随后进入 `P1-3 trim_messages` 的代码取证与官方调研。

### P1-3

- 当前状态：`已验证通过`
- 已完成：
  - 读取 `preprocess_context_nodes.py`、`preprocess_context_helpers.py`、`preprocess_query_bundle.py`、`kb_chat_context_seed.py`、`preprocess.py`，确认 KB Chat agentic 路径里原始 `messages` 的稳定消费点只有 preprocess 的 `merge_context` / `_extract_user_input`。
  - 交叉检索 `answer_subgraph_finalize.py`、`reflection_draft_generation.py`、`retrieval_subgraph.py` 等后续节点，确认 retrieval / answer 子图不再直接读取历史 `messages`，主要消费 `context_frame / merged_context / final_context`。
  - 查询官方文档与本地 introspection，确认 `trim_messages(...)` 当前签名支持 `strategy=\"last\"`、`token_counter=\"approximate\"` 或自定义计数器，以及 `start_on / end_on / include_system` 等序列约束参数。
- 追加完成：
  - 新增 `backend/tests/test_kb_preprocess_trim_messages.py`，先观察到 2 个 RED 失败，分别对应 preprocess 未做 token-aware trim、`merge_context` summary 未记录 `history_trimmed` 可观测字段。
  - 在 `preprocess_context_helpers.py` 新增 `trim_kb_preprocess_messages()`：先分离 persisted `SystemMessage` 摘要，再仅对 `HumanMessage/AIMessage` 对话消息执行 `trim_messages(strategy=\"last\", token_counter=\"approximate\")`。
  - 为极端小 budget 增加保底逻辑：若 `trim_messages` 结果为空，则至少保留最后一条 `HumanMessage`，确保 `_extract_user_input()` 与后续 preprocess 不丢当前问题。
  - `merge_context()` 改为基于裁剪后的 `messages` 继续执行 `_recent_turns()`、`build_context_seed_from_messages()`、summary / memory 合并，并把 `history_trimmed/history_input_tokens/history_output_tokens/history_budget_tokens/history_dropped_messages` 写入 `stage_summaries["merge_context"]`。
  - 定向测试 `uv run pytest tests/test_kb_preprocess_trim_messages.py` 通过，结果 `2 passed`。
  - 回归测试 `uv run pytest tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `33 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 当前边界：
  - 本点优先把 `trim_messages` 放在 `merge_context` 前段，先得到 token-aware 的历史消息窗口，再继续现有 summary / memory / question 合并逻辑。
  - 不在本点改 General Chat，也不顺手统一 `ContextBuilder.build_history_messages()` 与 KB Chat preprocess 两套历史裁剪实现。
- 下一步：只暂存 P1-3 相关源码/测试文件，创建单独 git 提交；随后进入 `P1-4 LLMToolSelectorMiddleware` 的代码取证与官方调研。

### P1-4

- 当前状态：`已验证通过`
- 已完成：
  - 读取 `general_chat_agent.py`、`research_runtime_factory.py`、`tool_calling/registry.py`，确认 `LLMToolSelectorMiddleware` 当前只需接入 General Chat 与 Deep Research 顶层 agent；KB Chat 不在本点范围。
  - 查询官方文档与本地源码，确认 `LLMToolSelectorMiddleware(model, max_tools, always_include)` 的实际签名，以及其在工具数较多时可通过小模型提前过滤 tool list。
  - 新增 `backend/tests/test_tool_selector_middleware.py`，先观察到 4 个 RED 失败，分别对应 selector settings 缺失、General Chat 构造器未接收新参数、Deep Research middleware 未装 selector。
  - 新增 `app/agents/tool_selection.py`，统一解析 `tool_selector_model_id` 并按 `tool_selector_enabled / tool_selector_trigger_tool_count / tool_selector_max_tools / tool_selector_always_include` 生成 selector middleware。
  - `Settings` 新增 `tool_selector_enabled/tool_selector_trigger_tool_count/tool_selector_max_tools/tool_selector_model_id/tool_selector_always_include`，其中 `tool_selector_always_include` 复用 `parse_string_list` 解析。
  - General Chat 顶层 agent 与 Deep Research runtime 接入 selector middleware；Deep Research 固定 `always_include=[\"record_runtime_activity\"]`，避免 live-board 关键工具被筛掉。
  - 为保持现有调用兼容，`build_general_chat_agent()` 的 selector 参数提供了默认值，旧测试与旧调用不需要同步传参也能工作。
  - 定向测试 `uv run pytest tests/test_tool_selector_middleware.py` 通过，结果 `4 passed`。
  - 回归测试 `uv run pytest tests/test_tool_selector_middleware.py tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `37 passed`。
  - 按仓库规则重建 backend graphify 图谱。
- 追加修正：
  - 提交前审查发现 General Chat 构造器虽然接入了 selector middleware，但临时 `Settings(...)` 未透传 `tool_selector_model_id`，导致 `TOOL_SELECTOR_MODEL_ID` 在 General Chat 路径上悬空。
  - 新增 `test_general_chat_passes_tool_selector_model_id_to_builder`，先把 `tool_selector_model_id` 与 `use_previous_response_id` 透传行为钉入测试。
  - `build_general_chat_agent()` 新增 `tool_selector_model_id` 与 `tool_selector_use_previous_response_id` 参数；General Chat execution / streaming / resume 调用点统一传入 settings 中的 selector model id 与当前 replay decision。
  - 修正后重新跑定向测试 `uv run pytest tests/test_tool_selector_middleware.py`，结果 `5 passed`。
  - 重新跑回归测试 `uv run pytest tests/test_tool_selector_middleware.py tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py`，结果 `38 passed, 1 warning`。
- 当前边界：
  - 本点只做顶层 agent 的 tool selector 装配，不改 KB Chat、自定义工具筛选策略或子代理级 selector。
  - MCP 的 HITL 边界仍由原有 `HumanInTheLoopMiddleware.interrupt_on` 控制，本点不改审批语义。
- 下一步：只暂存 P1-4 相关源码/测试文件，创建单独 git 提交；随后进入 `P1-5 Deep Research workspace 按需加载` 的代码取证与官方调研。

### P1-5

- 当前状态：`已验证通过`
- 已完成：
  - 读取 `research_runtime_workspace.py`、`research_runtime_context.py`、`research_runtime_types.py`、`deep_research_runtime.py`、`research_runtime_factory.py`，确认当前问题不在“缺少文件搜索工具”，而在于 `build_runtime_request_files_with_budget()` 会把非 priority 文件继续预置进 `request["files"]`，且 `StateBackend` 对未预置文件不可见。
  - 查询 Deep Agents / LangChain 本地包源码，确认 `create_deep_agent()` 默认已自带 `FilesystemMiddleware`，并验证 `StateBackend` 只有在 `invoke({"files": ...})` 预置后才可见文件；因此本点必须补一个 Deep Research 专用的 workspace overlay backend，而不是再叠一层重复 file-search middleware。
  - 新增 `backend/tests/test_research_runtime_workspace_on_demand.py`，先观察到 3 个 RED 阶段失败：`build_runtime_request_files_with_budget()` 缺少 on-demand 开关、缺少 `WorkspaceSeedBackend` 模块、seed backend 不能通过 `ls/glob/grep` 暴露静态文件。
  - `research_runtime_workspace.py` 新增 `include_non_priority_files` 开关；Deep Research 现在可以在本点选择只预置 priority 文件，并把其余路径记录到 `files_budget_snapshot.spilled_paths`。
  - 新增 `research_runtime_workspace_backend.py`，实现 `WorkspaceSeedRegistry` + `WorkspaceSeedBackend`：在 runtime 内按 `session_id` 暴露本次会话的静态 workspace 文件，`read/download/ls/glob/grep` 都优先读取 runtime 状态中的覆盖结果，缺失时再回退到 seed 文件视图。
  - `research_runtime_factory.py` 改为为 Deep Research 构造 session-aware overlay backend，并把 `workspace_seed_registry` 挂到 `DeepResearchRuntime`；同时移除会让 runtime-scoped `/skills/` 与 `/memories/` 脱离可见性的 `StoreBackend` 路由。
  - `deep_research_runtime.py` 在 `run_session()` 前后注册/清理当前 session 的完整 `workspace_files` 快照，并在 `_build_runtime_request_files(...)` 调用时启用 `include_non_priority_files=False`，让非 priority 文件真正转为 on-demand 读取。
  - 提交前审查确认 `SkillsMiddleware` 先 `ls("/skills/")` 再 `download_files(".../SKILL.md")`；原始 `WorkspaceSeedBackend.ls()` 只补 seed 文件、不补一级子目录，会让 runtime-scoped `/skills/` 与嵌套 workspace 路径失去 discoverability。
  - 补充 `backend/tests/test_research_runtime_workspace_on_demand.py`，新增 `/skills/` 子目录枚举、嵌套 workspace 子目录枚举，以及 `/skills/.../SKILL.md` / `/memories/...` 精确下载路径测试，并先观察到 `/skills/research-runtime/` 缺失的 RED 失败。
  - `research_runtime_workspace_backend.py` 的 `ls()` 现已补齐一级子目录条目，保持与 `StateBackend` 一致的“直接文件 + 直接子目录”语义，同时仍保留 runtime 状态覆盖 seed 文件的优先级。
  - 定向测试 `uv run pytest tests/test_research_runtime_workspace_on_demand.py -q` 通过，结果 `4 passed`。
  - 回归测试 `uv run pytest tests/test_research_runtime_workspace_on_demand.py tests/test_tool_selector_middleware.py tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `42 passed, 1 warning`。
  - 按仓库规则重建 backend graphify 图谱。
- 当前边界：
  - 本点只把 Deep Research 的首轮文件预置收紧到 priority 文件，并补上 non-priority 文件的 on-demand backend 可见性。
  - 不在本点参数化 `max_inline_chars`，也不引入 Prompt Caching 或额外的通用 middleware。
- 已提交：
  - `fbd7771 feat(context): load deep research workspace files on demand`

### P1-6

- 当前状态：`已验证通过`
- 已完成：
  - 读取 `research_runtime_types.py`、`deep_research_runtime.py`、`research_runtime_workspace.py`、`runtime_contract.py` 与 settings，确认 `max_inline_chars=6000` 是固定默认值，runner 没有从 settings 注入 `ResearchLargeResultPolicy`。
  - 查询 Deep Agents / LangChain / Anthropic 官方文档，确认长上下文应优先 offload 到文件系统并按需读取；本点只做阈值参数化，不提前做 Prompt Caching。
  - 新增 `backend/tests/test_research_runtime_large_result_policy.py`，先观察到 4 个 RED 失败：settings 字段缺失、`priority_inline_chars` 缺失、bootstrap priority inline 语义缺失、runner 未从 settings 注入 policy。
  - `Settings` 新增 `deep_research_large_result_max_inline_chars=2000` 与 `deep_research_priority_inline_chars=12000`，均使用 `ge=1`。
  - `ResearchLargeResultPolicy` 默认收紧为 `max_inline_chars=2000`，新增 `priority_inline_chars=12000`、构造校验与 `from_settings()`。
  - `build_deep_research_runtime_runner()` 现在从 settings 注入 `large_result_policy`。
  - `_build_bootstrap_workspace_file_entries()` 对 priority artifact 使用 `priority_inline_chars`，普通 artifact 继续使用 `max_inline_chars` 并按既有路径 spill。
  - 定向测试 `uv run pytest tests/test_research_runtime_large_result_policy.py -q` 通过，结果 `4 passed`。
  - 回归测试 `uv run pytest tests/test_research_runtime_large_result_policy.py tests/test_research_runtime_workspace_on_demand.py tests/test_tool_selector_middleware.py tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `46 passed, 1 warning`。
  - 按仓库规则重建 backend graphify 图谱。
- 当前边界：
  - 本点只参数化 Deep Research bootstrap artifact inline/spill 阈值，不改 P1-5 on-demand backend，不做 Prompt Caching。
  - `priority_inline_chars` 当前仅用于 bootstrap artifact 的 inline 判定，后续若要覆盖 request file priority token 预算应另起点处理。
- 已提交：
  - `1465196 feat(context): parameterize deep research spill thresholds`

### P1-7

- 当前状态：`已验证通过`
- 已完成：
  - 读取 `general_chat_agent.py`、General Chat 五处构造调用、`research_runtime_factory.py`、KB Chat 自建图调用点与本地 `langchain_anthropic` 包，确认官方 `AnthropicPromptCachingMiddleware` 可覆盖 `create_agent` / `create_deep_agent`，但不能直接覆盖 KB Chat 的直接 `.ainvoke()` 调用。
  - 查询 LangChain Anthropic 与 Anthropic Prompt Caching 官方文档，确认当前最佳实践是使用官方 middleware 标记 system/tool/cacheable blocks，而不是继续自写 `wrap_model_call`。
  - 新增 `backend/tests/test_anthropic_prompt_caching_middleware.py`，先观察到 4 个 RED 失败：settings 字段缺失、General Chat 构造器不接受 prompt caching 参数、Deep Research 未装 middleware。
  - 新增 `app/agents/prompt_caching.py`，统一构造 `AnthropicPromptCachingMiddleware(ttl=..., min_messages_to_cache=..., unsupported_model_behavior="ignore")`。
  - `Settings` 新增 `anthropic_prompt_caching_enabled=true`、`anthropic_prompt_cache_ttl="5m"`、`anthropic_prompt_cache_min_messages=0`，并校验 TTL 只能为 `5m` 或 `1h`。
  - General Chat 和 Deep Research 顶层 agent 接入 prompt caching middleware；General Chat normal/recovery/stream/resume-stream/resume 调用点均透传 settings。
  - 定向测试 `uv run pytest tests/test_anthropic_prompt_caching_middleware.py -q` 通过，结果 `4 passed`。
  - 回归测试 `uv run pytest tests/test_anthropic_prompt_caching_middleware.py tests/test_research_runtime_large_result_policy.py tests/test_research_runtime_workspace_on_demand.py tests/test_tool_selector_middleware.py tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `50 passed, 1 warning`。
  - 按仓库规则重建 backend graphify 图谱。
- 当前边界：
  - 本点只覆盖 General Chat 与 Deep Research 顶层 agent middleware。
  - KB Chat 自建图的 prompt caching 需要单独 wrapper 设计，不混入本点。
- 下一步：只暂存 P1-7 相关代码/测试文件并创建单独 git 提交；随后根据方案进入 P2 或下一未完成项。

### P2-1

- 当前状态：`已定位`
- 已完成初步恢复：
  - 读取控制面文件与 `上下文优化方案.md` P2 段落，确认 P0/P1 已完成，`P2-2` 已由 P1-4 覆盖，`P2-3` 需要等待/核实 SDK 支持。
  - 读取 backend graphify 报告与 KB Chat 记忆相关源码，确认当前自建记忆位于 `app.agents.kb_chat_memory`，preprocess 读取 `aget_kb_chat_memory()`，finalize 成功路径调用 `append_kb_chat_memory_entry()`。
  - 查询 LangMem 官方文档与本地包签名，确认 `create_memory_store_manager(...)`、`ReflectionExecutor(...)`、`MemoryStoreManager.asearch/aput/get_namespace` 可用；`create_manage_memory_tool/search_memory_tool` 更适合 agent 工具调用，本仓库 KB Chat 当前不是 ReAct agent，因此本点先迁移 manager/search 存储形态。
- 当前边界：
  - 不把 KB Chat 图整体改造成工具型 agent。
  - 不在本点接入 LangSmith/Grafana 指标，也不实现 Anthropic Context Management API 或 PII middleware。
- 失败记录：

### P2-3

- 当前状态：`已定位`
- 已完成：
  - 重新读取 `上下文优化方案.md`、`backend/graphify-out/GRAPH_REPORT.md`、`general_chat_agent.py`、`research_runtime_factory.py`、`kb_chat_memory.py`、`settings.py`，按当前磁盘事实恢复三条主链路的 memory / middleware / provider 接入点。
  - 使用本地已安装包 introspection 核对 `langchain-anthropic==1.4.0` 与 `anthropic==0.86.0` 的真实接口，确认 `ChatAnthropic` 已支持 `context_management` 字段。
  - 核对本地 `StateClaudeMemoryMiddleware` / `FilesystemClaudeMemoryMiddleware` 源码，确认它们明确属于 Anthropic memory tool 语义，并会注入 Anthropic 推荐 memory system prompt。
  - 查询 LangGraph / LangMem / Anthropic 官方资料，确认 `langmem + BaseStore` 才是 provider-agnostic 长期记忆主线；Anthropic context management / memory tool 只能作为 Claude provider 下的可选增强层。
- 当前结论：
  - `P2-3` 不能直接实现成 Claude-only memory。
  - 仓库当前正确方向是“通用 memory 主层，Anthropic context management 只做可选优化层”。
  - KB Chat 已在 `P2-1` 上完成这条主线的落地，不应回退。
- 当前边界：
  - 本阶段尚未修改生产代码，也未创建新的任务提交。
  - 在没有先把 `P2-3` 的实施目标收紧前，不进入编码，避免把 provider-specific 能力误接为系统统一抽象。
- 下一步：
  - 基于本轮调研结果，先向用户汇报 `P2-3` 应如何使用 LangChain 生态相关包实现。
  - 若用户认可纠偏后的方向，再进入该点的 TDD 与最小实现。
  - 曾尝试用 PowerShell `uv run python -c` one-liner 追加中文控制面内容，因字符串和编码解析导致 `SyntaxError: unterminated string literal`；已改用 `apply_patch`。
- 已完成：
  - 新增 `backend/tests/test_kb_chat_langmem_memory.py`，先观察到 2 个 RED 失败：`append_kb_chat_memory_entry()` 不接受 LangMem model 参数，且 `merge_context()` 仍读不到 LangMem fact。
  - 将 `kb_chat_memory.py` 迁移为 LangMem 适配层：新增 `KbChatFact` schema、`create_memory_store_manager(...)` manager 构造、`ReflectionExecutor` 后台反射提交、`create_search_memory_tool(...)` 读路径和 LangMem namespace config。
  - finalize 成功路径继续保持最佳努力写入，但现在传入 settings 并由 LangMem manager/executor 抽取长期事实，不再写旧 `kb_chat_memory:<thread>` 单 key payload。
  - preprocess 读取路径通过 LangMem search tool 按 `user_id + kb_scope` 搜索，并继续渲染到现有 `memory_snippet` / `memory_included` 语义。
  - `Settings` 新增 `KB_CHAT_MEMORY_MODEL_ID`、`KB_CHAT_MEMORY_SEARCH_LIMIT`、`KB_CHAT_MEMORY_MAX_STEPS`、`KB_CHAT_MEMORY_REFLECTION_DELAY_SECONDS`。
  - app shutdown 时关闭 KB Chat LangMem `ReflectionExecutor`，避免后台线程跨生命周期残留。
  - 定向测试 `uv run pytest tests/test_kb_chat_langmem_memory.py -q` 通过，结果 `3 passed, 1 warning`。
  - lint `uv run ruff check src/app/agents/kb_chat_memory.py src/app/agents/kb_chat_agentic/preprocess_context_nodes.py src/app/services/kb_chat_service_finalize.py src/app/core/settings.py src/app/bootstrap/lifespan.py tests/test_kb_chat_langmem_memory.py` 通过。
  - 回归测试 `uv run pytest tests/test_kb_chat_langmem_memory.py tests/test_anthropic_prompt_caching_middleware.py tests/test_research_runtime_large_result_policy.py tests/test_research_runtime_workspace_on_demand.py tests/test_tool_selector_middleware.py tests/test_kb_preprocess_trim_messages.py tests/test_retrieval_plan_budget_settings.py tests/test_retrieval_context_compress_budget.py tests/test_agent_model_safety.py tests/test_kb_chat_output_token_settings.py tests/test_retrieval_context_budget.py tests/test_context_budget_settings.py tests/test_summary_settings.py tests/test_general_chat_context_editing.py` 通过，结果 `53 passed, 1 warning`。
  - 按仓库规则重建 backend graphify 图谱，输出 `Rebuilt: 3809 nodes, 14508 edges, 96 communities`。
- 当前边界：
  - 本点没有把 KB Chat 改造成 ReAct agent，也没有让图节点自动调用 manage_memory 工具；写入仍由 finalize 成功路径触发，读路径由 preprocess 主动搜索。
  - 默认后台反射延迟为 300 秒；测试用 `reflection_delay_seconds=0` 只用于稳定验证同步写入路径。
- 下一步：只暂存 P2-1 相关源码、测试与 graphify 输出，创建单独 git 提交。

### P2-4

- 当前状态：`已验证通过`
- 已完成：
  - 根据用户最新要求，确认 `P2-3` 的 Anthropic provider 优化跳过，不进入实现。
  - 重新读取 `上下文优化方案.md` 中 `P2-4` 段落，确认方案原文包含“本地指标计算 + LangSmith + Grafana/日志面板 + 论文实验”多层工作，必须先收紧边界。
  - 读取 `context_builder.py`、`general_chat_service_runtime.py`、`kb_chat_service_observability.py`、`preprocess_context_nodes.py` 与现有测试，确认本点最小真实落点是：
    - 扩展 `ContextBuilder.build_metrics()` 的派生指标；
    - 扩展 `merge_context()` 的 memory 指标基础字段。
  - 读取本地 `LLMToolSelectorMiddleware` 源码，确认当前 middleware 不会暴露“选前/选后工具数”埋点；因此 `tool_selection_drop_rate` 不能在本点假实现。
  - 查询 LangSmith 官方资料，确认 tracing metadata 属于第二层对接；当前仓库虽已安装 `langsmith` 依赖，但源码中没有实际接入，因此本点先不做远端平台集成。
  - 新增/扩展测试：
    - `backend/tests/test_context_budget_settings.py`
    - `backend/tests/test_kb_chat_langmem_memory.py`
  - RED：`uv run pytest tests/test_context_budget_settings.py tests/test_kb_chat_langmem_memory.py -q`
    - 先观察到 2 个失败：
      - `metrics["derived"]` 缺失
      - `merge_context` 缺少 `memory_candidates` 等 memory 指标字段
  - GREEN：
    - `uv run pytest tests/test_context_budget_settings.py tests/test_kb_chat_langmem_memory.py -q`
    - 首次结果：`10 passed, 1 warning`
  - lint：
    - `uv run ruff check src/app/services/context_builder.py src/app/agents/kb_chat_memory.py src/app/agents/kb_chat_agentic/preprocess_context_nodes.py tests/test_context_budget_settings.py tests/test_kb_chat_langmem_memory.py`
    - 多次运行结果均为：`All checks passed!`
  - 回归：
    - `uv run pytest tests/test_context_budget_settings.py tests/test_kb_chat_langmem_memory.py tests/test_general_chat_context_editing.py tests/test_summary_settings.py tests/test_retrieval_context_budget.py tests/test_kb_preprocess_trim_messages.py tests/test_tool_selector_middleware.py tests/test_anthropic_prompt_caching_middleware.py -q`
    - 最终结果：`30 passed, 1 warning`
  - graphify：
    - 按仓库规则重建 `backend/graphify-out`
    - 最终结果：`Rebuilt: 3835 nodes, 14614 edges, 95 communities`
  - 提交前代码审查发现并已修复 2 个问题：
    - `ContextBuilder.build_metrics()` 新增 `derived` 后不能假设 `summary` bucket 一定存在；现已为 `summary/history` usage 和 truncation 补默认值，并新增 history-only 测试。
    - `memory_recall_precision` 不能把重复 fact 折叠和展示上限误算成 recall 降低；现已改为 distinct retained vs rendered 的同口径统计，并新增 `memory_retained_distinct`。
  - 修复后复验：
    - `uv run pytest tests/test_context_budget_settings.py tests/test_kb_chat_langmem_memory.py -q`
    - 结果：`11 passed, 1 warning`
    - `uv run pytest tests/test_context_budget_settings.py tests/test_kb_chat_langmem_memory.py tests/test_general_chat_context_editing.py tests/test_summary_settings.py tests/test_retrieval_context_budget.py tests/test_kb_preprocess_trim_messages.py tests/test_tool_selector_middleware.py tests/test_anthropic_prompt_caching_middleware.py -q`
    - 结果：`30 passed, 1 warning`
- 当前结论：
  - `P2-4` 的最小实现应先把上下文指标在本地 `metrics/stage_summaries` 中真实算出来。
  - 本点优先实现：
    - `context_utilization`
    - `truncation_rate`
    - `overall_truncated`
    - `memory_candidates / memory_retained / memory_rendered / memory_recall_precision`
- 当前边界：
  - 本点不做 LangSmith 远端对接、Grafana、论文实验补写、`tool_selection_drop_rate`、`prompt_cache_hit_rate`、Deep Research observability 扩改。
- 下一步：
  - 只暂存 `P2-4` 相关源码、测试与 graphify 产物，创建单独提交。
  - 提交后进入下一未完成点 `P2-5`，并在开始前重新做代码取证与官方资料调研。
