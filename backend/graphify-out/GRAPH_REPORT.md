# Graph Report - F:\毕设\code\backend  (2026-04-20)

## Corpus Check
- 361 files · ~583,539 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3835 nodes · 14614 edges · 95 communities detected
- Extraction: 38% EXTRACTED · 62% INFERRED · 0% AMBIGUOUS · INFERRED: 9111 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]

## God Nodes (most connected - your core abstractions)
1. `get()` - 563 edges
2. `Settings` - 376 edges
3. `QueryRewriteService` - 130 edges
4. `AppError` - 96 edges
5. `ResearchSourceTarget` - 79 edges
6. `QueryItem` - 75 edges
7. `get_settings()` - 72 edges
8. `ResearchService` - 67 edges
9. `ToolMeta` - 65 edges
10. `AgentRun` - 65 edges

## Surprising Connections (you probably didn't know these)
- `KB Chat 记忆辅助函数（基于 LangGraph Store）。  本模块维护的记忆载荷具备以下特性： - 结构化：使用 JSON 字典 - 有界：固定大` --uses--> `Settings`  [INFERRED]
  agents\kb_chat_memory.py → F:\毕设\code\backend\src\app\core\settings.py
- `使用 LangMem 从成功问答中抽取长期记忆。` --uses--> `Settings`  [INFERRED]
  F:\毕设\code\backend\src\app\agents\kb_chat_memory.py → F:\毕设\code\backend\src\app\core\settings.py
- `Agent 模型调用限流与降级 middleware 装配。` --uses--> `Settings`  [INFERRED]
  F:\毕设\code\backend\src\app\agents\model_safety.py → F:\毕设\code\backend\src\app\core\settings.py
- `Anthropic prompt caching middleware 装配。` --uses--> `Settings`  [INFERRED]
  F:\毕设\code\backend\src\app\agents\prompt_caching.py → F:\毕设\code\backend\src\app\core\settings.py
- `构建 Anthropic Prompt Caching middleware。` --uses--> `Settings`  [INFERRED]
  F:\毕设\code\backend\src\app\agents\prompt_caching.py → F:\毕设\code\backend\src\app\core\settings.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (407): budget_exceeded(), 返回 KB Chat 轮次 / 重试预算是否超限及原因。, ChatOpenAI, PendingClarification, append_compact_citations_to_answer(), _build_compact_entries(), _build_evidence_item(), _compact_locator() (+399 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (279): 合并后的最新结构基线。  Revision ID: 6f4b0d9e2c31 Revises: Create Date: 2026-02-18 15:02:27, upgrade(), downgrade(), 新增导入任务 outbox  Revision ID: 9b9a6f4f20d1 Revises: 6f4b0d9e2c31 Create Date: 2026, upgrade(), _backup_research_history(), downgrade(), 移除 research backend 实现相关持久化结构  Revision ID: a6b8c9d0e1f2 Revises: f3a2c1d4e5b6 C (+271 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (268): 统一 ChatModel 工厂（按全局模型配置选择 provider）。, _build_record_runtime_activity_tool(), _build_workspace_context_files(), _coerce_async_invoker(), _coerce_sync_invoker(), DeepResearchRuntimeRunner, _invoke_with_async_fallback(), _is_runtime_result_mapping() (+260 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (181): recover_stale_interactive_agent_runs(), recover_stale_interactive_agent_runs_on_startup(), get_app_resources(), require_app_resources(), set_app_resources(), is_running_in_worker_async_runtime(), initialize(), generate_contexts_for_chunks() (+173 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (215): BackendProtocol, WebSearchProviderStatusRead, WebSearchStatusRead, _build_runtime_context(), _load_runtime_tool_registry_for_session(), _load_tool_registry_for_session(), build_overall_web_search_status(), provider-aware 健康状态聚合。 (+207 more)

### Community 5 - "Community 5"
Cohesion: 0.02
Nodes (178): fail_stale_bootstrap_jobs(), create_chat_model(), create_chat_message(), create_chat_message_stream(), create_chat_session(), delete_chat_session(), _empty_stream_events(), get_chat_messages() (+170 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (212): KB Chat answer subgraph 生成、修复与提交节点。, KB Chat 答案生成子图。  该子图封装“草稿生成 → 审查 → 可选修复 → 提交”流程， 并通过写入 `reflection.action/reason, 为父级 KB Chat 图构建已编译的答案子图。, 为父级 KB Chat 图构建已编译的答案子图。, KB Chat answer subgraph 审查辅助。, KB Chat answer subgraph 审查节点。, KbChatAnswerSubgraphContext, KB Chat answer subgraph 共享辅助。 (+204 more)

### Community 7 - "Community 7"
Cohesion: 0.02
Nodes (166): AppEnv, from_value(), build_provider_error(), format_provider_error(), NormalizedSearchResult, provider_response_to_documents(), ProviderSearchReport, ProviderSearchResponse (+158 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (168): build_answer_subgraph(), _answer_commit(), _answer_repair(), _draft_generate(), 为父级 KB Chat 图构建已编译的答案子图。, _classify_structured_error(), _coalesce_paragraph_summary(), _count_unsupported_auxiliary_claims() (+160 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (161): AgentRun, AgentRunStatus, AgentRunType, 用于恢复过期交互式 AgentRun 记录的辅助函数。, AppResources, Base, ChatExporter, ChatMessage (+153 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (117): coref_rewrite(), normalize_rewrite(), 仅使用结构化 LLM 输出规范化查询；失败时回退到原始查询。, 使用 LLM 解析对话指代；失败时回退到原始查询。, resolve_reference(), rewrite(), AmbiguityResult, ComplexityRouteResult (+109 more)

### Community 11 - "Community 11"
Cohesion: 0.04
Nodes (76): initialize_worker_async_runtime(), _require_worker_async_runtime(), run_in_worker_async_runtime(), _runtime_thread_main(), shutdown_worker_async_runtime(), _WorkerAsyncRuntimeState, _build_celery_conf(), configure_celery_logging() (+68 more)

### Community 12 - "Community 12"
Cohesion: 0.04
Nodes (66): _CacheKey, create_chat_model_cached(), get_or_build(), _hash_key(), _previous_response_id_marker(), _resolve_max_retries_for_key(), _resolve_timeout_for_key(), _build_chat_openai_common_kwargs() (+58 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (67): FakeMessagesListChatModel, build_kb_chat_run_config(), build_kb_chat_run_context(), _coerce_int_setting(), KB Chat agentic graph 运行时辅助。, 为 KB Chat 构建 LangGraph 调用配置。      `recursion_limit` must stay at top-level con, 为 context_schema 驱动的节点运行时数据构建上下文。, build_context_seed() (+59 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (35): BaseVectorizer, _validate_content(), _build_semantic_cache_scope(), _get_semantic_cache_service(), _load_semantic_cache_pre_context(), _semantic_cache_citation_ids(), _semantic_cache_enabled(), _semantic_cache_evidence_fingerprint() (+27 more)

### Community 15 - "Community 15"
Cohesion: 0.1
Nodes (39): 用于处理过期 bootstrap 作业的 watchdog 任务。, EntryErrorRead, ManifestFileEntry, ManifestSourceType, KBBootstrapJob, KBBootstrapJobStatus, BootstrapSubmissionCreateResult, BootstrapUploadSessionResult (+31 more)

### Community 16 - "Community 16"
Cohesion: 0.06
Nodes (39): create_app(), clear(), stats(), _apply_cors_headers(), build_error_response(), _classify_dbapi_error(), ErrorCode, _is_ingestion_enum_schema_mismatch() (+31 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (21): 网页搜索 provider / tool 构建器。, _LocalRateLimiter, 网页搜索 Tavily client 与 provider 适配。, TavilySearchProviderAdapter, WebSearchClient, JinaReadArgs, WebCrawlArgs, WebExtractArgs (+13 more)

### Community 18 - "Community 18"
Cohesion: 0.06
Nodes (34): build_research_query_mesh(), _build_priority_context_paths(), build_runtime_context_guide(), build_runtime_context_snapshot(), _coerce_file_text(), _dedupe_paths(), _parse_json_array_payload(), _parse_json_object_payload() (+26 more)

### Community 19 - "Community 19"
Cohesion: 0.09
Nodes (26): resolve_summary_trim_tokens(), build_general_chat_agent(), build_anthropic_prompt_caching_middleware(), Anthropic prompt caching middleware 装配。, 构建 Anthropic Prompt Caching middleware。, SimpleNamespace, _NamedTool, test_deep_research_installs_anthropic_prompt_caching_middleware() (+18 more)

### Community 20 - "Community 20"
Cohesion: 0.38
Nodes (10): downgrade(), _drop_backup_tables(), reintroduce research session tables  Revision ID: 38f4aa0f8d91 Revises: a6b8c9d0, _report_json_uuid_sql(), _restore_research_artifacts_from_backup(), _restore_research_events_from_backup(), _restore_research_reports_from_backup(), _restore_research_sessions_from_backup() (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.36
Nodes (8): _backfill_batch_rollups(), downgrade(), _downgrade_batch_status_enum(), _downgrade_doc_status_enum(), make ingestion status semantics explicit  Revision ID: c7d8e9f0a1b2 Revises: b3c, upgrade(), _upgrade_batch_status_enum(), _upgrade_doc_status_enum()

### Community 22 - "Community 22"
Cohesion: 0.46
Nodes (7): do_run_migrations(), get_url(), include_object(), _object_table_name(), run_migrations(), run_migrations_offline(), run_migrations_online()

### Community 23 - "Community 23"
Cohesion: 0.5
Nodes (1): add research event idempotency index  Revision ID: 19a4c2e7d8f1 Revises: f4c6d8e

### Community 24 - "Community 24"
Cohesion: 0.5
Nodes (1): remove research kb selection fields  Revision ID: 1c2d3e4f5a6b Revises: 38f4aa0f

### Community 25 - "Community 25"
Cohesion: 0.5
Nodes (1): add clarifying to research session status  Revision ID: 2f6a9c8d1b4e Revises: 1c

### Community 26 - "Community 26"
Cohesion: 0.5
Nodes (1): add chat messages recent index  Revision ID: 4b8e1d2c3f4a Revises: 19a4c2e7d8f1

### Community 27 - "Community 27"
Cohesion: 0.5
Nodes (1): add llama.cpp model provider  Revision ID: b3c4d5e6f7a8 Revises: a9e7c4d2b1f0 Cr

### Community 28 - "Community 28"
Cohesion: 0.5
Nodes (1): add plan_ready to research session status  Revision ID: c1d2e3f4a5b6 Revises:

### Community 29 - "Community 29"
Cohesion: 0.5
Nodes (1): 支持每个提供商配置多个模型  Revision ID: e5a1b7d3c4f2 Revises: d1e8b6c4a9f0 Create Date: 2026

### Community 30 - "Community 30"
Cohesion: 0.5
Nodes (1): add succeeded to ingestion task outbox status  Revision ID: e8f9a0b1c2d3 Revises

### Community 31 - "Community 31"
Cohesion: 0.5
Nodes (1): 新增聊天请求去重表  Revision ID: f3a2c1d4e5b6 Revises: e5a1b7d3c4f2 Create Date: 2026-02-

### Community 32 - "Community 32"
Cohesion: 0.5
Nodes (1): add anthropic model provider  Revision ID: f4b2c1d9e8a7 Revises: c1d2e3f4a5b6 Cr

### Community 33 - "Community 33"
Cohesion: 0.5
Nodes (1): drop tool extension observability config  Revision ID: f4c6d8e0a1b2 Revises: e8f

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): KB Chat trace 节点展示契约辅助函数。

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): 构建带静态 seed 文件视图的 backend。

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): 由答案段落推导出的 latest-only 渲染元数据。

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): 研究工具输出 excerpt_candidates。

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): critic subagent 模板加载。

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): shared_contract 与主 / subagent 提示词加载检查。

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): runtime_user 去除先写大纲再搜证据的约束。

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): researcher subagent 模板加载。

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): ResearchCanonicalCitation excerpt 契约测试。

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): ResearchClaimMap / ResearchEvidenceLedger 契约测试。

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): run_session 中不再有 prefetch 分支。

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): quality_snapshot artifact 落盘。

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): recovery 不再做 prefetch / 全量回捞。

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): runtime_context snapshot 对齐新 layout。

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): research_runtime_skills 内容对齐新 pipeline。

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): 流式增量类型枚举，对齐 LangChain 消息内容块格式。

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): 类型化流式增量结构，用于 SSE delta 事件。      Attributes:         kind: 增量类型，区分思考/回答/工具调用/工具结果

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): 判断节点输出的原始文本是否应视为答案内容。

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): 从 LLM token chunk 提取结构化 StreamDelta 列表。      解析规则（LangChain 1.2.6 标准）：     - rea

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): 从消息列表构建工具调用摘要的思考 delta。

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): 合并 LangGraph updates 中的 state 片段。

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): 从 LLM token chunk 中提取文本。

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): 合并 updates chunk，返回 interrupt 列表。

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): 轮询数据并输出 update/final 事件。

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): 收集 heartbeat 发送统计，用于下游可观测性。

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): LangGraph 检查点管理器。  提供 AsyncPostgresSaver 的统一管理，支持检查点持久化和恢复。

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): 构建一个小而稳定的摘要，避免直接暴露原始 checkpoint 状态。

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): KB Chat 图相关模块的导入烟雾测试。

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): 当数据库尚未初始化或缺少 ingestion 枚举时抛出。

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): 当数据库中的 ingestion 枚举与应用契约不一致时抛出。

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (1): 构建一个小而稳定的摘要，避免直接暴露原始 checkpoint 状态。

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (1): 为 Milvus 构建安全的过滤表达式。          - Always enforces kb_id scope when provided.

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (1): 确保 collection 存在并对齐最新 schema。

### Community 94 - "Community 94"
Cohesion: 1.0
Nodes (1): 稀疏检索：仅 BM25，无需 embedding。

## Knowledge Gaps
- **152 isolated node(s):** `add research event idempotency index  Revision ID: 19a4c2e7d8f1 Revises: f4c6d8e`, `remove research kb selection fields  Revision ID: 1c2d3e4f5a6b Revises: 38f4aa0f`, `add clarifying to research session status  Revision ID: 2f6a9c8d1b4e Revises: 1c`, `reintroduce research session tables  Revision ID: 38f4aa0f8d91 Revises: a6b8c9d0`, `add chat messages recent index  Revision ID: 4b8e1d2c3f4a Revises: 19a4c2e7d8f1` (+147 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 34`** (2 nodes): `kb_chat_trace_display_contract.py`, `KB Chat trace 节点展示契约辅助函数。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (2 nodes): `stream_heartbeat_payload()`, `chat_dependencies.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (2 nodes): `system.py`, `get_queue_health()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (2 nodes): `__init__.py`, `create_app()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (2 nodes): `general_chat_service_contracts.py`, `_as_str_dict()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (2 nodes): `kb_chat_service_method_bindings.py`, `bind_kb_chat_service_methods()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `main.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `deps.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `api.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `构建带静态 seed 文件视图的 backend。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `由答案段落推导出的 latest-only 渲染元数据。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `研究工具输出 excerpt_candidates。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `critic subagent 模板加载。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `shared_contract 与主 / subagent 提示词加载检查。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `runtime_user 去除先写大纲再搜证据的约束。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `researcher subagent 模板加载。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `ResearchCanonicalCitation excerpt 契约测试。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `ResearchClaimMap / ResearchEvidenceLedger 契约测试。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `run_session 中不再有 prefetch 分支。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `quality_snapshot artifact 落盘。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `recovery 不再做 prefetch / 全量回捞。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `runtime_context snapshot 对齐新 layout。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `research_runtime_skills 内容对齐新 pipeline。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `流式增量类型枚举，对齐 LangChain 消息内容块格式。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `类型化流式增量结构，用于 SSE delta 事件。      Attributes:         kind: 增量类型，区分思考/回答/工具调用/工具结果`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `判断节点输出的原始文本是否应视为答案内容。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `从 LLM token chunk 提取结构化 StreamDelta 列表。      解析规则（LangChain 1.2.6 标准）：     - rea`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `从消息列表构建工具调用摘要的思考 delta。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `合并 LangGraph updates 中的 state 片段。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `从 LLM token chunk 中提取文本。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `合并 updates chunk，返回 interrupt 列表。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `轮询数据并输出 update/final 事件。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `收集 heartbeat 发送统计，用于下游可观测性。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `LangGraph 检查点管理器。  提供 AsyncPostgresSaver 的统一管理，支持检查点持久化和恢复。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `构建一个小而稳定的摘要，避免直接暴露原始 checkpoint 状态。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `KB Chat 图相关模块的导入烟雾测试。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `当数据库尚未初始化或缺少 ingestion 枚举时抛出。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `当数据库中的 ingestion 枚举与应用契约不一致时抛出。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (1 nodes): `构建一个小而稳定的摘要，避免直接暴露原始 checkpoint 状态。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (1 nodes): `为 Milvus 构建安全的过滤表达式。          - Always enforces kb_id scope when provided.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (1 nodes): `确保 collection 存在并对齐最新 schema。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 94`** (1 nodes): `稀疏检索：仅 BM25，无需 embedding。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Community 6` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.165) - this node is a cross-community bridge._
- **Why does `get()` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 15`, `Community 16`, `Community 17`, `Community 18`, `Community 19`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Community 3` to `Community 1`, `Community 2`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 16`, `Community 22`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 556 inferred relationships involving `get()` (e.g. with `build_pending_tool_calls()` and `_route_after_preprocess_subgraph()`) actually correct?**
  _`get()` has 556 INFERRED edges - model-reasoned connections that need verification._
- **Are the 420 inferred relationships involving `str` (e.g. with `_route_after_preprocess_subgraph()` and `build_kb_chat_run_context()`) actually correct?**
  _`str` has 420 INFERRED edges - model-reasoned connections that need verification._
- **Are the 372 inferred relationships involving `Settings` (e.g. with `构建 HITL interrupt_on 配置：仅拦截 MCP 扩展工具。` and `KbChatFact`) actually correct?**
  _`Settings` has 372 INFERRED edges - model-reasoned connections that need verification._
- **Are the 109 inferred relationships involving `QueryRewriteService` (e.g. with `KbChatGraphContext` and `KB Chat 流程图第 4 阶段的检索子图。`) actually correct?**
  _`QueryRewriteService` has 109 INFERRED edges - model-reasoned connections that need verification._