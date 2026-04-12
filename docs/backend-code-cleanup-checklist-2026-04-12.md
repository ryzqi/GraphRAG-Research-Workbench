# Backend 逐文件安全清理清单

## 说明

- 唯一事实源：`git ls-files backend`（初始基线）
- 当前纳入清单的文件总数：382
- 口径：仅仓库一方后端代码与直接相关配置；排除 `backend/.venv`、缓存、构建产物；清理过程中已删除的条目仍保留在清单中
- 勾选规则：仅当该文件已完成分析，且已确认“无需修改”或“已安全清理并完成对应验证”时，才可勾选

## Root

- [x] backend/alembic.ini
- [x] backend/celerybeat-schedule (已删除；Celery Beat 运行时 SQLite 调度产物)
- [x] backend/pyproject.toml (已清理未使用依赖)
- [x] backend/uv.lock (已随依赖清理同步更新)

## Alembic

- [x] backend/alembic/env.py
- [x] backend/alembic/script.py.mako
- [x] backend/alembic/versions/1c2d3e4f5a6b_remove_research_kb_selection_fields.py
- [x] backend/alembic/versions/2f6a9c8d1b4e_add_clarifying_to_research_session_status.py
- [x] backend/alembic/versions/38f4aa0f8d91_reintroduce_research_session_tables.py
- [x] backend/alembic/versions/6f4b0d9e2c31_squashed_latest_schema_baseline.py
- [x] backend/alembic/versions/9b9a6f4f20d1_add_ingestion_task_outbox.py
- [x] backend/alembic/versions/a6b8c9d0e1f2_remove_research_stack.py
- [x] backend/alembic/versions/a9e7c4d2b1f0_add_research_task_outbox.py
- [x] backend/alembic/versions/b3c4d5e6f7a8_add_llamacpp_model_provider.py
- [x] backend/alembic/versions/b7c3d1a9f2e4_add_model_runtime_config_tables.py
- [x] backend/alembic/versions/c1d2e3f4a5b6_add_plan_ready_to_research_session_status.py
- [x] backend/alembic/versions/c4d7a3f1b8e9_remove_evaluations_and_evidence_compare.py
- [x] backend/alembic/versions/d1e8b6c4a9f0_add_index_rebuild_task_outbox.py
- [x] backend/alembic/versions/e5a1b7d3c4f2_support_multiple_models_per_provider.py
- [x] backend/alembic/versions/f3a2c1d4e5b6_add_chat_request_dedup_table.py
- [x] backend/alembic/versions/f4b2c1d9e8a7_add_anthropic_model_provider.py

## src/app

- [x] backend/src/app/__init__.py
- [x] backend/src/app/.gitignore
- [x] backend/src/app/main.py

### agents

- [x] backend/src/app/agents/__init__.py
- [x] backend/src/app/agents/answer_subgraph.py (已删除；单层桥接已内联)
- [x] backend/src/app/agents/base.py (已删除；仓内无消费者)
- [x] backend/src/app/agents/general_chat_agent.py
- [x] backend/src/app/agents/kb_chat_agentic/__init__.py
- [x] backend/src/app/agents/kb_chat_agentic/answer_subgraph.py
- [x] backend/src/app/agents/kb_chat_agentic/budget.py
- [x] backend/src/app/agents/kb_chat_agentic/dispatch_fuse.py
- [x] backend/src/app/agents/kb_chat_agentic/json_safety.py
- [x] backend/src/app/agents/kb_chat_agentic/preprocess.py
- [x] backend/src/app/agents/kb_chat_agentic/reflection.py
- [x] backend/src/app/agents/kb_chat_agentic/runtime_config.py
- [x] backend/src/app/agents/kb_chat_agentic/schemas.py
- [x] backend/src/app/agents/kb_chat_agentic/tool_loop.py
- [x] backend/src/app/agents/kb_chat_agentic_graph.py (已清理桥接导入)
- [x] backend/src/app/agents/kb_chat_agentic_graph_runtime.py
- [x] backend/src/app/agents/kb_chat_agentic_state.py
- [x] backend/src/app/agents/kb_chat_contracts.py
- [x] backend/src/app/agents/kb_chat_graph.py
- [x] backend/src/app/agents/kb_chat_memory.py
- [x] backend/src/app/agents/kb_chat_trace_display_contract.py
- [x] backend/src/app/agents/kb_chat_trace_display_input.py
- [x] backend/src/app/agents/kb_chat_trace_display_output.py
- [x] backend/src/app/agents/kb_chat_trace_display_shared.py
- [x] backend/src/app/agents/kb_chat_trace_nodes.py
- [x] backend/src/app/agents/preprocess_subgraph.py
- [x] backend/src/app/agents/retrieval_subgraph.py
- [x] backend/src/app/agents/tool_calling/__init__.py (已清理无用导出)
- [x] backend/src/app/agents/tool_calling/builder.py (已删除；仓内无消费者)
- [x] backend/src/app/agents/tool_calling/registry.py
- [x] backend/src/app/agents/tool_calling/utils.py
- [x] backend/src/app/agents/tool_calling/web_tool_payloads.py
- [x] backend/src/app/agents/tools/__init__.py
- [x] backend/src/app/agents/tools/kb_retrieve.py
- [x] backend/src/app/agents/tools/report_generate.py
- [x] backend/src/app/agents/tools/research_tools.py
- [x] backend/src/app/agents/tools/system_time.py
- [x] backend/src/app/agents/tools/web_search.py
- [x] backend/src/app/agents/tools/web_search_builders.py
- [x] backend/src/app/agents/tools/web_search_client.py
- [x] backend/src/app/agents/tools/web_search_models.py
- [x] backend/src/app/agents/tools/web_search_providers/__init__.py
- [x] backend/src/app/agents/tools/web_search_providers/base.py
- [x] backend/src/app/agents/tools/web_search_providers/jina_provider.py
- [x] backend/src/app/agents/tools/web_search_providers/searxng_provider.py
- [x] backend/src/app/agents/tools/web_search_utils.py

### api

- [x] backend/src/app/api/__init__.py
- [x] backend/src/app/api/deps.py
- [x] backend/src/app/api/sse.py
- [x] backend/src/app/api/v1/__init__.py
- [x] backend/src/app/api/v1/api.py
- [x] backend/src/app/api/v1/endpoints/__init__.py
- [x] backend/src/app/api/v1/endpoints/chat_dependencies.py
- [x] backend/src/app/api/v1/endpoints/chats.py
- [x] backend/src/app/api/v1/endpoints/checkpoints.py
- [x] backend/src/app/api/v1/endpoints/exports.py
- [x] backend/src/app/api/v1/endpoints/extensions.py
- [x] backend/src/app/api/v1/endpoints/health.py
- [x] backend/src/app/api/v1/endpoints/index_rebuilds.py
- [x] backend/src/app/api/v1/endpoints/ingestion_batches.py
- [x] backend/src/app/api/v1/endpoints/kb_bootstrap_jobs.py
- [x] backend/src/app/api/v1/endpoints/knowledge_bases.py
- [x] backend/src/app/api/v1/endpoints/knowledge_updates.py
- [x] backend/src/app/api/v1/endpoints/materials.py
- [x] backend/src/app/api/v1/endpoints/model_config.py
- [x] backend/src/app/api/v1/endpoints/research.py
- [x] backend/src/app/api/v1/endpoints/system.py

### bootstrap

- [x] backend/src/app/bootstrap/__init__.py
- [x] backend/src/app/bootstrap/app_factory.py
- [x] backend/src/app/bootstrap/lifespan.py

### core

- [x] backend/src/app/core/__init__.py
- [x] backend/src/app/core/checkpoint.py
- [x] backend/src/app/core/errors.py
- [x] backend/src/app/core/logging.py
- [x] backend/src/app/core/memory_store.py
- [x] backend/src/app/core/middleware/__init__.py
- [x] backend/src/app/core/middleware/request_id.py
- [x] backend/src/app/core/model_config_errors.py
- [x] backend/src/app/core/secrets.py
- [x] backend/src/app/core/security.py (已删除；仓内无消费者)
- [x] backend/src/app/core/settings.py (已清理孤儿配置字段)
- [x] backend/src/app/core/tracing.py (已删除；仓内无消费者)
- [x] backend/src/app/core/uvicorn_loop.py
- [x] backend/src/app/core/validators.py

### db

- [x] backend/src/app/db/__init__.py
- [x] backend/src/app/db/base.py
- [x] backend/src/app/db/enums.py
- [x] backend/src/app/db/schema_guard.py
- [x] backend/src/app/db/session.py

### integrations

- [x] backend/src/app/integrations/__init__.py
- [x] backend/src/app/integrations/chat_model_factory.py
- [x] backend/src/app/integrations/embedding_client.py
- [x] backend/src/app/integrations/http_client.py
- [x] backend/src/app/integrations/langchain_profiles.py
- [x] backend/src/app/integrations/llamacpp_chat_model.py
- [x] backend/src/app/integrations/llm_client.py
- [x] backend/src/app/integrations/mcp_adapters.py
- [x] backend/src/app/integrations/milvus_client.py
- [x] backend/src/app/integrations/model_health_probe.py
- [x] backend/src/app/integrations/model_runtime_config.py
- [x] backend/src/app/integrations/object_storage.py
- [x] backend/src/app/integrations/redis_client.py
- [x] backend/src/app/integrations/rerank_client.py

### models

- [x] backend/src/app/models/__init__.py
- [x] backend/src/app/models/agent_run.py
- [x] backend/src/app/models/chat_message.py
- [x] backend/src/app/models/chat_request_dedup.py
- [x] backend/src/app/models/chat_session.py
- [x] backend/src/app/models/document_chunk.py
- [x] backend/src/app/models/evidence.py
- [x] backend/src/app/models/export_job.py
- [x] backend/src/app/models/index_rebuild_job.py
- [x] backend/src/app/models/index_rebuild_task_outbox.py
- [x] backend/src/app/models/ingestion_batch.py
- [x] backend/src/app/models/ingestion_task_outbox.py
- [x] backend/src/app/models/kb_bootstrap_job.py
- [x] backend/src/app/models/kb_config_snapshot.py
- [x] backend/src/app/models/knowledge_base.py
- [x] backend/src/app/models/knowledge_update_proposal.py
- [x] backend/src/app/models/model_config.py
- [x] backend/src/app/models/research_artifact.py
- [x] backend/src/app/models/research_event.py
- [x] backend/src/app/models/research_session.py
- [x] backend/src/app/models/research_task_outbox.py
- [x] backend/src/app/models/source_material.py
- [x] backend/src/app/models/tool_extension.py

### prompts

- [x] backend/src/app/prompts/__init__.py
- [x] backend/src/app/prompts/loader.py
- [x] backend/src/app/prompts/templates/general_chat/system.yaml
- [x] backend/src/app/prompts/templates/ingestion/contextual_embedding.yaml
- [x] backend/src/app/prompts/templates/kb_chat/ambiguity_decision.yaml
- [x] backend/src/app/prompts/templates/kb_chat/answer_review.yaml
- [x] backend/src/app/prompts/templates/kb_chat/citation_review.yaml
- [x] backend/src/app/prompts/templates/kb_chat/complexity_classify.yaml
- [x] backend/src/app/prompts/templates/kb_chat/context_compress.yaml
- [x] backend/src/app/prompts/templates/kb_chat/context_merge.yaml
- [x] backend/src/app/prompts/templates/kb_chat/decomposition.yaml
- [x] backend/src/app/prompts/templates/kb_chat/hyde.yaml
- [x] backend/src/app/prompts/templates/kb_chat/multi_query.yaml
- [x] backend/src/app/prompts/templates/kb_chat/normalize_query.yaml
- [x] backend/src/app/prompts/templates/kb_chat/resolve_reference.yaml
- [x] backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml
- [x] backend/src/app/prompts/templates/kb_chat/system.yaml
- [x] backend/src/app/prompts/templates/kb_chat/transform_query.yaml
- [x] backend/src/app/prompts/templates/research/analysis_notes_md.yaml
- [x] backend/src/app/prompts/templates/research/claim_map_md.yaml
- [x] backend/src/app/prompts/templates/research/coverage_md.yaml
- [x] backend/src/app/prompts/templates/research/evidence_ledger_md.yaml
- [x] backend/src/app/prompts/templates/research/mission_md.yaml
- [x] backend/src/app/prompts/templates/research/plan_md.yaml
- [x] backend/src/app/prompts/templates/research/query_map_md.yaml
- [x] backend/src/app/prompts/templates/research/query_mesh_breadth_compare.yaml
- [x] backend/src/app/prompts/templates/research/query_mesh_depth_fallback.yaml
- [x] backend/src/app/prompts/templates/research/query_mesh_depth_subtask_evidence.yaml
- [x] backend/src/app/prompts/templates/research/query_mesh_subtask_verification.yaml
- [x] backend/src/app/prompts/templates/research/query_mesh_verification_crosscheck.yaml
- [x] backend/src/app/prompts/templates/research/query_mesh_verification_risks.yaml
- [x] backend/src/app/prompts/templates/research/report_coverage_gaps_section_md.yaml
- [x] backend/src/app/prompts/templates/research/report_draft_md.yaml
- [x] backend/src/app/prompts/templates/research/report_evidence_section_md.yaml
- [x] backend/src/app/prompts/templates/research/report_findings_section_md.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_compiled_md.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_default_section_json.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_fallback_md.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_fallback_sections_json.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_format_brief.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_format_detailed.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_format_standard.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_invalid_schema_error_message.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_no_citations.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_no_findings.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_parse_error_message.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_section_md.yaml
- [x] backend/src/app/prompts/templates/research/report_generate_unknown_source.yaml
- [x] backend/src/app/prompts/templates/research/report_md.yaml
- [x] backend/src/app/prompts/templates/research/report_outline_md.yaml
- [x] backend/src/app/prompts/templates/research/report_references_section_md.yaml
- [x] backend/src/app/prompts/templates/research/runtime_system.yaml
- [x] backend/src/app/prompts/templates/research/runtime_user.yaml
- [x] backend/src/app/prompts/templates/research/scoper_system.yaml
- [x] backend/src/app/prompts/templates/research/scoper_user.yaml
- [x] backend/src/app/prompts/templates/retrieval/query_rewrite.yaml
- [x] backend/src/app/prompts/templates/tools/report_generate.yaml

### schemas

- [x] backend/src/app/schemas/__init__.py
- [x] backend/src/app/schemas/chats.py
- [x] backend/src/app/schemas/checkpoints.py
- [x] backend/src/app/schemas/exports.py
- [x] backend/src/app/schemas/extensions.py
- [x] backend/src/app/schemas/index_rebuilds.py
- [x] backend/src/app/schemas/ingestion_batches.py
- [x] backend/src/app/schemas/kb_bootstrap_jobs.py
- [x] backend/src/app/schemas/knowledge_bases.py
- [x] backend/src/app/schemas/knowledge_updates.py
- [x] backend/src/app/schemas/materials.py
- [x] backend/src/app/schemas/model_config.py
- [x] backend/src/app/schemas/pagination.py
- [x] backend/src/app/schemas/query_enhancement.py
- [x] backend/src/app/schemas/research.py
- [x] backend/src/app/schemas/system.py

### search

- [x] backend/src/app/search/web/__init__.py
- [x] backend/src/app/search/web/citations.py
- [x] backend/src/app/search/web/contracts.py
- [x] backend/src/app/search/web/documents.py
- [x] backend/src/app/search/web/enrichment.py
- [x] backend/src/app/search/web/fusion.py
- [x] backend/src/app/search/web/health.py
- [x] backend/src/app/search/web/pipeline.py
- [x] backend/src/app/search/web/query_rewrite.py
- [x] backend/src/app/search/web/rerank.py
- [x] backend/src/app/search/web/retrievers/__init__.py
- [x] backend/src/app/search/web/retrievers/base.py
- [x] backend/src/app/search/web/retrievers/searxng.py
- [x] backend/src/app/search/web/retrievers/tavily.py

### services

- [x] backend/src/app/services/__init__.py
- [x] backend/src/app/services/agent_run_recovery.py
- [x] backend/src/app/services/chat_replay_policy.py
- [x] backend/src/app/services/chunk_persistence_service.py
- [x] backend/src/app/services/chunking.py
- [x] backend/src/app/services/context_builder.py
- [x] backend/src/app/services/contextual_embedding_service.py
- [x] backend/src/app/services/conversation_summary_service.py
- [x] backend/src/app/services/deep_research_runtime.py
- [x] backend/src/app/services/evidence_guardrails.py
- [x] backend/src/app/services/export_service.py
- [x] backend/src/app/services/exporters/__init__.py
- [x] backend/src/app/services/exporters/chat_exporter.py
- [x] backend/src/app/services/exporters/research_exporter.py
- [x] backend/src/app/services/extension_service.py
- [x] backend/src/app/services/general_chat_service.py
- [x] backend/src/app/services/general_chat_service_contracts.py
- [x] backend/src/app/services/general_chat_service_dedup.py
- [x] backend/src/app/services/general_chat_service_execution.py
- [x] backend/src/app/services/general_chat_service_interrupts.py
- [x] backend/src/app/services/general_chat_service_runtime.py
- [x] backend/src/app/services/index_rebuild_service.py
- [x] backend/src/app/services/ingestion_batch_service.py
- [x] backend/src/app/services/ingestion_batch_service_contracts.py
- [x] backend/src/app/services/ingestion_batch_service_prepare.py
- [x] backend/src/app/services/ingestion_batch_service_status.py
- [x] backend/src/app/services/ingestion_batch_service_url_security.py
- [x] backend/src/app/services/ingestion_contract.py
- [x] backend/src/app/services/kb_answer_paragraphs.py
- [x] backend/src/app/services/kb_bootstrap_job_service.py
- [x] backend/src/app/services/kb_chat_live_artifacts.py (已删除；仓内无引用)
- [x] backend/src/app/services/kb_chat_service.py
- [x] backend/src/app/services/kb_chat_service_answer_stream_cached.py
- [x] backend/src/app/services/kb_chat_service_answer_stream_postprocess.py
- [x] backend/src/app/services/kb_chat_service_citations.py
- [x] backend/src/app/services/kb_chat_service_contracts.py
- [x] backend/src/app/services/kb_chat_service_execution.py
- [x] backend/src/app/services/kb_chat_service_finalize.py
- [x] backend/src/app/services/kb_chat_service_message_ops.py
- [x] backend/src/app/services/kb_chat_service_method_bindings.py
- [x] backend/src/app/services/kb_chat_service_observability.py
- [x] backend/src/app/services/kb_chat_service_schema.py
- [x] backend/src/app/services/kb_chat_service_semantic_cache.py
- [x] backend/src/app/services/kb_chat_service_stream_protocol.py
- [x] backend/src/app/services/kb_evidence.py
- [x] backend/src/app/services/knowledge_base_service.py
- [x] backend/src/app/services/knowledge_update_service.py
- [x] backend/src/app/services/material_service.py
- [x] backend/src/app/services/message_normalizer.py
- [x] backend/src/app/services/model_config_service.py
- [x] backend/src/app/services/parsing/__init__.py
- [x] backend/src/app/services/parsing/errors.py
- [x] backend/src/app/services/parsing/material_parser.py
- [x] backend/src/app/services/parsing/types.py
- [x] backend/src/app/services/query_dependent_collections.py
- [x] backend/src/app/services/query_rewrite_basic_ops.py
- [x] backend/src/app/services/query_rewrite_contracts.py
- [x] backend/src/app/services/query_rewrite_items.py
- [x] backend/src/app/services/query_rewrite_planning_ops.py
- [x] backend/src/app/services/query_rewrite_service.py
- [x] backend/src/app/services/query_rewrite_structured.py
- [x] backend/src/app/services/query_rewrite_text.py
- [x] backend/src/app/services/queue_health_service.py
- [x] backend/src/app/services/research_artifact_store.py
- [x] backend/src/app/services/research_event_store.py
- [x] backend/src/app/services/research_finalizer.py
- [x] backend/src/app/services/research_observability.py
- [x] backend/src/app/services/research_planner.py
- [x] backend/src/app/services/research_planner_types.py
- [x] backend/src/app/services/research_presentation_snapshot.py (已清理零引用 helper)
- [x] backend/src/app/services/research_query_mesh.py
- [x] backend/src/app/services/research_replay.py
- [x] backend/src/app/services/research_report_compiler.py
- [x] backend/src/app/services/research_runtime_context.py
- [x] backend/src/app/services/research_runtime_factory.py
- [x] backend/src/app/services/research_runtime_recovery.py
- [x] backend/src/app/services/research_runtime_skills.py
- [x] backend/src/app/services/research_runtime_spill.py
- [x] backend/src/app/services/research_runtime_types.py
- [x] backend/src/app/services/research_runtime_workspace.py
- [x] backend/src/app/services/research_service.py (已清理零引用私有 helper)
- [x] backend/src/app/services/research_service_contracts.py
- [x] backend/src/app/services/research_service_execution.py
- [x] backend/src/app/services/research_service_runtime.py
- [x] backend/src/app/services/research_service_session_ops.py
- [x] backend/src/app/services/research_source_bundle.py
- [x] backend/src/app/services/research_verification.py
- [x] backend/src/app/services/research_workspace_files.py (已清理零引用常量)
- [x] backend/src/app/services/retrieval_service.py
- [x] backend/src/app/services/retrieval_service_context.py
- [x] backend/src/app/services/retrieval_service_contracts.py
- [x] backend/src/app/services/retrieval_service_layer_ops.py
- [x] backend/src/app/services/retrieval_service_retrieve_ops.py
- [x] backend/src/app/services/retrieval_service_runtime.py
- [x] backend/src/app/services/retrieval_service_strategy_ops.py
- [x] backend/src/app/services/semantic_cache/__init__.py
- [x] backend/src/app/services/semantic_cache/models.py
- [x] backend/src/app/services/semantic_cache/policy.py
- [x] backend/src/app/services/semantic_cache/redisvl_backend.py
- [x] backend/src/app/services/semantic_cache/service.py
- [x] backend/src/app/services/streaming.py
- [x] backend/src/app/services/web_search_status_service.py

### utils

- [x] backend/src/app/utils/__init__.py
- [x] backend/src/app/utils/text_sanitization.py
- [x] backend/src/app/utils/token_counter.py

### worker

- [x] backend/src/app/worker/__init__.py
- [x] backend/src/app/worker/celery_app.py
- [x] backend/src/app/worker/task_resources.py
- [x] backend/src/app/worker/tasks/__init__.py
- [x] backend/src/app/worker/tasks/bootstrap_watchdog.py
- [x] backend/src/app/worker/tasks/contextual_retry.py
- [x] backend/src/app/worker/tasks/embedding_inputs.py
- [x] backend/src/app/worker/tasks/export.py
- [x] backend/src/app/worker/tasks/index_rebuild.py
- [x] backend/src/app/worker/tasks/index_rebuild_outbox_dispatcher.py
- [x] backend/src/app/worker/tasks/ingestion_batches.py
- [x] backend/src/app/worker/tasks/ingestion_outbox_dispatcher.py
- [x] backend/src/app/worker/tasks/ingestion_watchdog.py
- [x] backend/src/app/worker/tasks/kb_bootstrap_jobs.py
- [x] backend/src/app/worker/tasks/research.py
- [x] backend/src/app/worker/tasks/research_outbox_dispatcher.py

## tests

- [x] backend/tests/test_app_factory.py
- [x] backend/tests/test_chat_endpoint_dependencies.py
- [x] backend/tests/test_chat_model_factory_llamacpp.py
- [x] backend/tests/test_general_chat_service_helper_binding.py
- [x] backend/tests/test_general_chat_service_helper_modules.py
- [x] backend/tests/test_ingestion_batch_service_helper_modules.py
- [x] backend/tests/test_kb_chat_agentic_graph_helper_modules.py
- [x] backend/tests/test_kb_chat_trace_display_contract_helpers.py
- [x] backend/tests/test_llamacpp_reasoning.py
- [x] backend/tests/test_model_config_service_llamacpp.py
- [x] backend/tests/test_query_rewrite_helper_modules.py
- [x] backend/tests/test_research_agent_runs_removal.py
- [x] backend/tests/test_research_artifact_normalization.py
- [x] backend/tests/test_research_clarification_policy.py
- [x] backend/tests/test_research_runtime_context_management.py
- [x] backend/tests/test_research_runtime_factory.py
- [x] backend/tests/test_research_runtime_helper_modules.py
- [x] backend/tests/test_research_runtime_report_enrichment.py
- [x] backend/tests/test_research_service_contracts_module.py
- [x] backend/tests/test_research_service_execution_helpers.py
- [x] backend/tests/test_research_service_finalization_contract.py
- [x] backend/tests/test_research_service_session_ops_module.py
- [x] backend/tests/test_retrieval_service_helper_modules.py
- [x] backend/tests/test_web_search_helper_modules.py
