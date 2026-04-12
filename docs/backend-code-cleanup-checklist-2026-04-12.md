# Backend 逐文件安全清理清单

## 说明

- 唯一事实源：`git ls-files backend`
- 当前纳入清单的文件总数：378
- 口径：仅仓库一方后端代码与直接相关配置；排除 `backend/.venv`、缓存、构建产物
- 勾选规则：仅当该文件已完成分析，且已确认“无需修改”或“已安全清理并完成对应验证”时，才可勾选

## Root

- [ ] backend/alembic.ini
- [ ] backend/pyproject.toml

## Alembic

- [ ] backend/alembic/env.py
- [ ] backend/alembic/versions/1c2d3e4f5a6b_remove_research_kb_selection_fields.py
- [ ] backend/alembic/versions/2f6a9c8d1b4e_add_clarifying_to_research_session_status.py
- [ ] backend/alembic/versions/38f4aa0f8d91_reintroduce_research_session_tables.py
- [ ] backend/alembic/versions/6f4b0d9e2c31_squashed_latest_schema_baseline.py
- [ ] backend/alembic/versions/9b9a6f4f20d1_add_ingestion_task_outbox.py
- [ ] backend/alembic/versions/a6b8c9d0e1f2_remove_research_stack.py
- [ ] backend/alembic/versions/a9e7c4d2b1f0_add_research_task_outbox.py
- [ ] backend/alembic/versions/b3c4d5e6f7a8_add_llamacpp_model_provider.py
- [ ] backend/alembic/versions/b7c3d1a9f2e4_add_model_runtime_config_tables.py
- [ ] backend/alembic/versions/c1d2e3f4a5b6_add_plan_ready_to_research_session_status.py
- [ ] backend/alembic/versions/c4d7a3f1b8e9_remove_evaluations_and_evidence_compare.py
- [ ] backend/alembic/versions/d1e8b6c4a9f0_add_index_rebuild_task_outbox.py
- [ ] backend/alembic/versions/e5a1b7d3c4f2_support_multiple_models_per_provider.py
- [ ] backend/alembic/versions/f3a2c1d4e5b6_add_chat_request_dedup_table.py
- [ ] backend/alembic/versions/f4b2c1d9e8a7_add_anthropic_model_provider.py

## src/app

- [ ] backend/src/app/__init__.py
- [ ] backend/src/app/main.py

### agents

- [ ] backend/src/app/agents/__init__.py
- [ ] backend/src/app/agents/answer_subgraph.py
- [ ] backend/src/app/agents/base.py
- [ ] backend/src/app/agents/general_chat_agent.py
- [ ] backend/src/app/agents/kb_chat_agentic/__init__.py
- [ ] backend/src/app/agents/kb_chat_agentic/answer_subgraph.py
- [ ] backend/src/app/agents/kb_chat_agentic/budget.py
- [ ] backend/src/app/agents/kb_chat_agentic/dispatch_fuse.py
- [ ] backend/src/app/agents/kb_chat_agentic/json_safety.py
- [ ] backend/src/app/agents/kb_chat_agentic/preprocess.py
- [ ] backend/src/app/agents/kb_chat_agentic/reflection.py
- [ ] backend/src/app/agents/kb_chat_agentic/runtime_config.py
- [ ] backend/src/app/agents/kb_chat_agentic/schemas.py
- [ ] backend/src/app/agents/kb_chat_agentic/tool_loop.py
- [ ] backend/src/app/agents/kb_chat_agentic_graph.py
- [ ] backend/src/app/agents/kb_chat_agentic_graph_runtime.py
- [ ] backend/src/app/agents/kb_chat_agentic_state.py
- [ ] backend/src/app/agents/kb_chat_contracts.py
- [ ] backend/src/app/agents/kb_chat_graph.py
- [ ] backend/src/app/agents/kb_chat_memory.py
- [ ] backend/src/app/agents/kb_chat_trace_display_contract.py
- [ ] backend/src/app/agents/kb_chat_trace_display_input.py
- [ ] backend/src/app/agents/kb_chat_trace_display_output.py
- [ ] backend/src/app/agents/kb_chat_trace_display_shared.py
- [ ] backend/src/app/agents/kb_chat_trace_nodes.py
- [ ] backend/src/app/agents/preprocess_subgraph.py
- [ ] backend/src/app/agents/retrieval_subgraph.py
- [ ] backend/src/app/agents/tool_calling/__init__.py
- [ ] backend/src/app/agents/tool_calling/builder.py
- [ ] backend/src/app/agents/tool_calling/registry.py
- [ ] backend/src/app/agents/tool_calling/utils.py
- [ ] backend/src/app/agents/tool_calling/web_tool_payloads.py
- [ ] backend/src/app/agents/tools/__init__.py
- [ ] backend/src/app/agents/tools/kb_retrieve.py
- [ ] backend/src/app/agents/tools/report_generate.py
- [ ] backend/src/app/agents/tools/research_tools.py
- [ ] backend/src/app/agents/tools/system_time.py
- [ ] backend/src/app/agents/tools/web_search.py
- [ ] backend/src/app/agents/tools/web_search_builders.py
- [ ] backend/src/app/agents/tools/web_search_client.py
- [ ] backend/src/app/agents/tools/web_search_models.py
- [ ] backend/src/app/agents/tools/web_search_providers/__init__.py
- [ ] backend/src/app/agents/tools/web_search_providers/base.py
- [ ] backend/src/app/agents/tools/web_search_providers/jina_provider.py
- [ ] backend/src/app/agents/tools/web_search_providers/searxng_provider.py
- [ ] backend/src/app/agents/tools/web_search_utils.py

### api

- [ ] backend/src/app/api/__init__.py
- [ ] backend/src/app/api/deps.py
- [ ] backend/src/app/api/sse.py
- [ ] backend/src/app/api/v1/__init__.py
- [ ] backend/src/app/api/v1/api.py
- [ ] backend/src/app/api/v1/endpoints/__init__.py
- [ ] backend/src/app/api/v1/endpoints/chat_dependencies.py
- [ ] backend/src/app/api/v1/endpoints/chats.py
- [ ] backend/src/app/api/v1/endpoints/checkpoints.py
- [ ] backend/src/app/api/v1/endpoints/exports.py
- [ ] backend/src/app/api/v1/endpoints/extensions.py
- [ ] backend/src/app/api/v1/endpoints/health.py
- [ ] backend/src/app/api/v1/endpoints/index_rebuilds.py
- [ ] backend/src/app/api/v1/endpoints/ingestion_batches.py
- [ ] backend/src/app/api/v1/endpoints/kb_bootstrap_jobs.py
- [ ] backend/src/app/api/v1/endpoints/knowledge_bases.py
- [ ] backend/src/app/api/v1/endpoints/knowledge_updates.py
- [ ] backend/src/app/api/v1/endpoints/materials.py
- [ ] backend/src/app/api/v1/endpoints/model_config.py
- [ ] backend/src/app/api/v1/endpoints/research.py
- [ ] backend/src/app/api/v1/endpoints/system.py

### bootstrap

- [ ] backend/src/app/bootstrap/__init__.py
- [ ] backend/src/app/bootstrap/app_factory.py
- [ ] backend/src/app/bootstrap/lifespan.py

### core

- [ ] backend/src/app/core/__init__.py
- [ ] backend/src/app/core/checkpoint.py
- [ ] backend/src/app/core/errors.py
- [ ] backend/src/app/core/logging.py
- [ ] backend/src/app/core/memory_store.py
- [ ] backend/src/app/core/middleware/__init__.py
- [ ] backend/src/app/core/middleware/request_id.py
- [ ] backend/src/app/core/model_config_errors.py
- [ ] backend/src/app/core/secrets.py
- [ ] backend/src/app/core/security.py
- [ ] backend/src/app/core/settings.py
- [ ] backend/src/app/core/tracing.py
- [ ] backend/src/app/core/uvicorn_loop.py
- [ ] backend/src/app/core/validators.py

### db

- [ ] backend/src/app/db/__init__.py
- [ ] backend/src/app/db/base.py
- [ ] backend/src/app/db/enums.py
- [ ] backend/src/app/db/schema_guard.py
- [ ] backend/src/app/db/session.py

### integrations

- [ ] backend/src/app/integrations/__init__.py
- [ ] backend/src/app/integrations/chat_model_factory.py
- [ ] backend/src/app/integrations/embedding_client.py
- [ ] backend/src/app/integrations/http_client.py
- [ ] backend/src/app/integrations/langchain_profiles.py
- [ ] backend/src/app/integrations/llamacpp_chat_model.py
- [ ] backend/src/app/integrations/llm_client.py
- [ ] backend/src/app/integrations/mcp_adapters.py
- [ ] backend/src/app/integrations/milvus_client.py
- [ ] backend/src/app/integrations/model_health_probe.py
- [ ] backend/src/app/integrations/model_runtime_config.py
- [ ] backend/src/app/integrations/object_storage.py
- [ ] backend/src/app/integrations/redis_client.py
- [ ] backend/src/app/integrations/rerank_client.py

### models

- [ ] backend/src/app/models/__init__.py
- [ ] backend/src/app/models/agent_run.py
- [ ] backend/src/app/models/chat_message.py
- [ ] backend/src/app/models/chat_request_dedup.py
- [ ] backend/src/app/models/chat_session.py
- [ ] backend/src/app/models/document_chunk.py
- [ ] backend/src/app/models/evidence.py
- [ ] backend/src/app/models/export_job.py
- [ ] backend/src/app/models/index_rebuild_job.py
- [ ] backend/src/app/models/index_rebuild_task_outbox.py
- [ ] backend/src/app/models/ingestion_batch.py
- [ ] backend/src/app/models/ingestion_task_outbox.py
- [ ] backend/src/app/models/kb_bootstrap_job.py
- [ ] backend/src/app/models/kb_config_snapshot.py
- [ ] backend/src/app/models/knowledge_base.py
- [ ] backend/src/app/models/knowledge_update_proposal.py
- [ ] backend/src/app/models/model_config.py
- [ ] backend/src/app/models/research_artifact.py
- [ ] backend/src/app/models/research_event.py
- [ ] backend/src/app/models/research_session.py
- [ ] backend/src/app/models/research_task_outbox.py
- [ ] backend/src/app/models/source_material.py
- [ ] backend/src/app/models/tool_extension.py

### prompts

- [ ] backend/src/app/prompts/__init__.py
- [ ] backend/src/app/prompts/loader.py
- [ ] backend/src/app/prompts/templates/general_chat/system.yaml
- [ ] backend/src/app/prompts/templates/ingestion/contextual_embedding.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/ambiguity_decision.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/answer_review.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/citation_review.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/complexity_classify.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/context_compress.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/context_merge.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/decomposition.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/hyde.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/multi_query.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/normalize_query.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/resolve_reference.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/system.yaml
- [ ] backend/src/app/prompts/templates/kb_chat/transform_query.yaml
- [ ] backend/src/app/prompts/templates/research/analysis_notes_md.yaml
- [ ] backend/src/app/prompts/templates/research/claim_map_md.yaml
- [ ] backend/src/app/prompts/templates/research/coverage_md.yaml
- [ ] backend/src/app/prompts/templates/research/evidence_ledger_md.yaml
- [ ] backend/src/app/prompts/templates/research/mission_md.yaml
- [ ] backend/src/app/prompts/templates/research/plan_md.yaml
- [ ] backend/src/app/prompts/templates/research/query_map_md.yaml
- [ ] backend/src/app/prompts/templates/research/query_mesh_breadth_compare.yaml
- [ ] backend/src/app/prompts/templates/research/query_mesh_depth_fallback.yaml
- [ ] backend/src/app/prompts/templates/research/query_mesh_depth_subtask_evidence.yaml
- [ ] backend/src/app/prompts/templates/research/query_mesh_subtask_verification.yaml
- [ ] backend/src/app/prompts/templates/research/query_mesh_verification_crosscheck.yaml
- [ ] backend/src/app/prompts/templates/research/query_mesh_verification_risks.yaml
- [ ] backend/src/app/prompts/templates/research/report_coverage_gaps_section_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_draft_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_evidence_section_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_findings_section_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_compiled_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_default_section_json.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_fallback_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_fallback_sections_json.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_format_brief.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_format_detailed.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_format_standard.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_invalid_schema_error_message.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_no_citations.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_no_findings.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_parse_error_message.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_section_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_generate_unknown_source.yaml
- [ ] backend/src/app/prompts/templates/research/report_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_outline_md.yaml
- [ ] backend/src/app/prompts/templates/research/report_references_section_md.yaml
- [ ] backend/src/app/prompts/templates/research/runtime_system.yaml
- [ ] backend/src/app/prompts/templates/research/runtime_user.yaml
- [ ] backend/src/app/prompts/templates/research/scoper_system.yaml
- [ ] backend/src/app/prompts/templates/research/scoper_user.yaml
- [ ] backend/src/app/prompts/templates/retrieval/query_rewrite.yaml
- [ ] backend/src/app/prompts/templates/tools/report_generate.yaml

### schemas

- [ ] backend/src/app/schemas/__init__.py
- [ ] backend/src/app/schemas/chats.py
- [ ] backend/src/app/schemas/checkpoints.py
- [ ] backend/src/app/schemas/exports.py
- [ ] backend/src/app/schemas/extensions.py
- [ ] backend/src/app/schemas/index_rebuilds.py
- [ ] backend/src/app/schemas/ingestion_batches.py
- [ ] backend/src/app/schemas/kb_bootstrap_jobs.py
- [ ] backend/src/app/schemas/knowledge_bases.py
- [ ] backend/src/app/schemas/knowledge_updates.py
- [ ] backend/src/app/schemas/materials.py
- [ ] backend/src/app/schemas/model_config.py
- [ ] backend/src/app/schemas/pagination.py
- [ ] backend/src/app/schemas/query_enhancement.py
- [ ] backend/src/app/schemas/research.py
- [ ] backend/src/app/schemas/system.py

### search

- [ ] backend/src/app/search/web/__init__.py
- [ ] backend/src/app/search/web/citations.py
- [ ] backend/src/app/search/web/contracts.py
- [ ] backend/src/app/search/web/documents.py
- [ ] backend/src/app/search/web/enrichment.py
- [ ] backend/src/app/search/web/fusion.py
- [ ] backend/src/app/search/web/health.py
- [ ] backend/src/app/search/web/pipeline.py
- [ ] backend/src/app/search/web/query_rewrite.py
- [ ] backend/src/app/search/web/rerank.py
- [ ] backend/src/app/search/web/retrievers/__init__.py
- [ ] backend/src/app/search/web/retrievers/base.py
- [ ] backend/src/app/search/web/retrievers/searxng.py
- [ ] backend/src/app/search/web/retrievers/tavily.py

### services

- [ ] backend/src/app/services/__init__.py
- [ ] backend/src/app/services/agent_run_recovery.py
- [ ] backend/src/app/services/chat_replay_policy.py
- [ ] backend/src/app/services/chunk_persistence_service.py
- [ ] backend/src/app/services/chunking.py
- [ ] backend/src/app/services/context_builder.py
- [ ] backend/src/app/services/contextual_embedding_service.py
- [ ] backend/src/app/services/conversation_summary_service.py
- [ ] backend/src/app/services/deep_research_runtime.py
- [ ] backend/src/app/services/evidence_guardrails.py
- [ ] backend/src/app/services/export_service.py
- [ ] backend/src/app/services/exporters/__init__.py
- [ ] backend/src/app/services/exporters/chat_exporter.py
- [ ] backend/src/app/services/exporters/research_exporter.py
- [ ] backend/src/app/services/extension_service.py
- [ ] backend/src/app/services/general_chat_service.py
- [ ] backend/src/app/services/general_chat_service_contracts.py
- [ ] backend/src/app/services/general_chat_service_dedup.py
- [ ] backend/src/app/services/general_chat_service_execution.py
- [ ] backend/src/app/services/general_chat_service_interrupts.py
- [ ] backend/src/app/services/general_chat_service_runtime.py
- [ ] backend/src/app/services/index_rebuild_service.py
- [ ] backend/src/app/services/ingestion_batch_service.py
- [ ] backend/src/app/services/ingestion_batch_service_contracts.py
- [ ] backend/src/app/services/ingestion_batch_service_prepare.py
- [ ] backend/src/app/services/ingestion_batch_service_status.py
- [ ] backend/src/app/services/ingestion_batch_service_url_security.py
- [ ] backend/src/app/services/ingestion_contract.py
- [ ] backend/src/app/services/kb_answer_paragraphs.py
- [ ] backend/src/app/services/kb_bootstrap_job_service.py
- [ ] backend/src/app/services/kb_chat_live_artifacts.py
- [ ] backend/src/app/services/kb_chat_service.py
- [ ] backend/src/app/services/kb_chat_service_answer_stream_cached.py
- [ ] backend/src/app/services/kb_chat_service_answer_stream_postprocess.py
- [ ] backend/src/app/services/kb_chat_service_citations.py
- [ ] backend/src/app/services/kb_chat_service_contracts.py
- [ ] backend/src/app/services/kb_chat_service_execution.py
- [ ] backend/src/app/services/kb_chat_service_finalize.py
- [ ] backend/src/app/services/kb_chat_service_message_ops.py
- [ ] backend/src/app/services/kb_chat_service_method_bindings.py
- [ ] backend/src/app/services/kb_chat_service_observability.py
- [ ] backend/src/app/services/kb_chat_service_schema.py
- [ ] backend/src/app/services/kb_chat_service_semantic_cache.py
- [ ] backend/src/app/services/kb_chat_service_stream_protocol.py
- [ ] backend/src/app/services/kb_evidence.py
- [ ] backend/src/app/services/knowledge_base_service.py
- [ ] backend/src/app/services/knowledge_update_service.py
- [ ] backend/src/app/services/material_service.py
- [ ] backend/src/app/services/message_normalizer.py
- [ ] backend/src/app/services/model_config_service.py
- [ ] backend/src/app/services/parsing/__init__.py
- [ ] backend/src/app/services/parsing/errors.py
- [ ] backend/src/app/services/parsing/material_parser.py
- [ ] backend/src/app/services/parsing/types.py
- [ ] backend/src/app/services/query_dependent_collections.py
- [ ] backend/src/app/services/query_rewrite_basic_ops.py
- [ ] backend/src/app/services/query_rewrite_contracts.py
- [ ] backend/src/app/services/query_rewrite_items.py
- [ ] backend/src/app/services/query_rewrite_planning_ops.py
- [ ] backend/src/app/services/query_rewrite_service.py
- [ ] backend/src/app/services/query_rewrite_structured.py
- [ ] backend/src/app/services/query_rewrite_text.py
- [ ] backend/src/app/services/queue_health_service.py
- [ ] backend/src/app/services/research_artifact_store.py
- [ ] backend/src/app/services/research_event_store.py
- [ ] backend/src/app/services/research_finalizer.py
- [ ] backend/src/app/services/research_observability.py
- [ ] backend/src/app/services/research_planner.py
- [ ] backend/src/app/services/research_planner_types.py
- [ ] backend/src/app/services/research_presentation_snapshot.py
- [ ] backend/src/app/services/research_query_mesh.py
- [ ] backend/src/app/services/research_replay.py
- [ ] backend/src/app/services/research_report_compiler.py
- [ ] backend/src/app/services/research_runtime_context.py
- [ ] backend/src/app/services/research_runtime_factory.py
- [ ] backend/src/app/services/research_runtime_recovery.py
- [ ] backend/src/app/services/research_runtime_skills.py
- [ ] backend/src/app/services/research_runtime_spill.py
- [ ] backend/src/app/services/research_runtime_types.py
- [ ] backend/src/app/services/research_runtime_workspace.py
- [ ] backend/src/app/services/research_service.py
- [ ] backend/src/app/services/research_service_contracts.py
- [ ] backend/src/app/services/research_service_execution.py
- [ ] backend/src/app/services/research_service_runtime.py
- [ ] backend/src/app/services/research_service_session_ops.py
- [ ] backend/src/app/services/research_source_bundle.py
- [ ] backend/src/app/services/research_verification.py
- [ ] backend/src/app/services/research_workspace_files.py
- [ ] backend/src/app/services/retrieval_service.py
- [ ] backend/src/app/services/retrieval_service_context.py
- [ ] backend/src/app/services/retrieval_service_contracts.py
- [ ] backend/src/app/services/retrieval_service_layer_ops.py
- [ ] backend/src/app/services/retrieval_service_retrieve_ops.py
- [ ] backend/src/app/services/retrieval_service_runtime.py
- [ ] backend/src/app/services/retrieval_service_strategy_ops.py
- [ ] backend/src/app/services/semantic_cache/__init__.py
- [ ] backend/src/app/services/semantic_cache/models.py
- [ ] backend/src/app/services/semantic_cache/policy.py
- [ ] backend/src/app/services/semantic_cache/redisvl_backend.py
- [ ] backend/src/app/services/semantic_cache/service.py
- [ ] backend/src/app/services/streaming.py
- [ ] backend/src/app/services/web_search_status_service.py

### utils

- [ ] backend/src/app/utils/__init__.py
- [ ] backend/src/app/utils/text_sanitization.py
- [ ] backend/src/app/utils/token_counter.py

### worker

- [ ] backend/src/app/worker/__init__.py
- [ ] backend/src/app/worker/celery_app.py
- [ ] backend/src/app/worker/task_resources.py
- [ ] backend/src/app/worker/tasks/__init__.py
- [ ] backend/src/app/worker/tasks/bootstrap_watchdog.py
- [ ] backend/src/app/worker/tasks/contextual_retry.py
- [ ] backend/src/app/worker/tasks/embedding_inputs.py
- [ ] backend/src/app/worker/tasks/export.py
- [ ] backend/src/app/worker/tasks/index_rebuild.py
- [ ] backend/src/app/worker/tasks/index_rebuild_outbox_dispatcher.py
- [ ] backend/src/app/worker/tasks/ingestion_batches.py
- [ ] backend/src/app/worker/tasks/ingestion_outbox_dispatcher.py
- [ ] backend/src/app/worker/tasks/ingestion_watchdog.py
- [ ] backend/src/app/worker/tasks/kb_bootstrap_jobs.py
- [ ] backend/src/app/worker/tasks/research.py
- [ ] backend/src/app/worker/tasks/research_outbox_dispatcher.py

## tests

- [ ] backend/tests/test_app_factory.py
- [ ] backend/tests/test_chat_endpoint_dependencies.py
- [ ] backend/tests/test_chat_model_factory_llamacpp.py
- [ ] backend/tests/test_general_chat_service_helper_binding.py
- [ ] backend/tests/test_general_chat_service_helper_modules.py
- [ ] backend/tests/test_ingestion_batch_service_helper_modules.py
- [ ] backend/tests/test_kb_chat_agentic_graph_helper_modules.py
- [ ] backend/tests/test_kb_chat_trace_display_contract_helpers.py
- [ ] backend/tests/test_llamacpp_reasoning.py
- [ ] backend/tests/test_model_config_service_llamacpp.py
- [ ] backend/tests/test_query_rewrite_helper_modules.py
- [ ] backend/tests/test_research_agent_runs_removal.py
- [ ] backend/tests/test_research_artifact_normalization.py
- [ ] backend/tests/test_research_clarification_policy.py
- [ ] backend/tests/test_research_runtime_context_management.py
- [ ] backend/tests/test_research_runtime_factory.py
- [ ] backend/tests/test_research_runtime_helper_modules.py
- [ ] backend/tests/test_research_runtime_report_enrichment.py
- [ ] backend/tests/test_research_service_contracts_module.py
- [ ] backend/tests/test_research_service_execution_helpers.py
- [ ] backend/tests/test_research_service_finalization_contract.py
- [ ] backend/tests/test_research_service_session_ops_module.py
- [ ] backend/tests/test_retrieval_service_helper_modules.py
- [ ] backend/tests/test_web_search_helper_modules.py
