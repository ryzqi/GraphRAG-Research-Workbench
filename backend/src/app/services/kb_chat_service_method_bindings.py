from __future__ import annotations

from app.services import kb_chat_service_citations as kb_citations
from app.services import kb_chat_service_execution as kb_execution
from app.services import kb_chat_service_finalize as kb_finalize
from app.services import kb_chat_service_message_ops as kb_message_ops
from app.services import kb_chat_service_observability as kb_observability
from app.services import kb_chat_service_schema as kb_schema
from app.services import kb_chat_service_semantic_cache as kb_semantic_cache
from app.services import kb_chat_service_stream_protocol as kb_stream_protocol


def bind_kb_chat_service_methods(cls: type) -> None:
    method_groups = (
        (
            kb_semantic_cache,
            (
                '_resolve_session_kb_chat_config',
                '_to_retrieval_overrides',
                '_semantic_cache_enabled',
                '_get_semantic_cache_service',
                '_semantic_cache_threshold',
                '_semantic_cache_ttl_seconds',
                '_semantic_cache_recent_turns',
                '_load_semantic_cache_pre_context',
                '_semantic_cache_citation_ids',
                '_semantic_cache_evidence_fingerprint',
                '_semantic_cache_source_run_id',
                '_semantic_config_fingerprint',
                '_semantic_kb_version',
                '_build_semantic_cache_scope',
                '_semantic_cache_lookup',
                '_write_semantic_cache_entry',
                '_release_retrieval_buffer',
            ),
        ),
        (
            kb_schema,
            (
                '_build_terminal_event_payload',
                '_build_graph_schema_payload',
                '_build_drawable_graph_from_builder',
                '_build_drawable_graph_from_compiled_xray',
                '_build_schema_drawable_graph',
                '_build_trace_snapshot',
            ),
        ),
        (
            kb_observability,
            (
                '_ensure_no_pending_tool_approval',
                '_build_retrieval_stage_summary',
                '_safe_percent',
                '_safe_rate',
                '_extract_run_latency_ms',
                '_calc_percentile',
                '_compute_p95_latency_increase_pct',
                '_compute_route_consistency',
                '_compute_final_state_consistency',
                '_compute_clarification_consistency',
                '_build_gray_release_gate',
                '_refresh_semantic_cache_hit_metrics',
                '_persist_gray_release_anomaly_sample',
                '_build_observability',
                '_build_retry_cache_metrics',
                '_build_protocol_metrics',
                '_apply_guardrail_metrics',
                '_persist_guardrail_run',
            ),
        ),
        (
            kb_execution,
            (
                '_apply_gray_release_rollback_policy',
                '_sanitize_checkpoint_messages',
                '_sanitize_checkpoint_state',
                '_build_checkpoint_restore_audit',
                '_resolve_kb_chat_user_id',
                '_get_running_kb_chat_run',
                '_ensure_no_running_kb_chat_run',
                '_ensure_kb_chat_resume_target_valid',
                '_prepare_kb_chat_execution',
            ),
        ),
        (
            kb_message_ops,
            (
                '_load_history',
                '_to_langchain_message',
                '_default_clarification_message',
                '_coerce_pending_clarification',
                '_resolve_terminal_reason',
                '_extract_clarification_pending',
                '_resolve_terminal_run_status',
                '_build_no_evidence_response',
            ),
        ),
        (
            kb_stream_protocol,
            (
                '_semantic_cache_entry_admission_reason',
                '_calculate_stream_progress',
                '_shorten_stream_text',
                '_build_node_io_summary',
                '_build_stream_state_payload',
                '_build_protocol_event_payload',
                '_build_node_io_payload',
                '_json_safe_custom_payload',
                '_build_graph_stream_options',
                '_build_step_payload_from_task_event',
                '_normalize_graph_stream_event',
                '_normalize_stream_namespace',
                '_build_stream_execution_scope',
                '_remember_stream_execution',
                '_resolve_stream_execution_id',
                '_build_scoped_node_path',
                '_build_active_path',
                '_resolve_stream_state_node_name',
                '_apply_stream_state_node_io',
                '_apply_stream_state_step',
                '_safe_non_negative_int',
            ),
        ),
        (
            kb_citations,
            (
                '_normalize_optional_text',
                '_extract_locator_material_title',
                '_extract_filename_stem',
                '_extract_citation_source',
                '_extract_citation_title',
                '_load_material_title_map',
                '_extract_citation_page_hint',
                '_append_citation_sources',
                '_extract_last_good_answer',
                '_clarification_round_count',
                '_persist_clarification_pending',
                '_persist_semantic_cache_hit',
                '_build_semantic_cache_display_output_items',
                '_emit_semantic_cache_fast_path',
            ),
        ),
        (
            kb_finalize,
            (
                '_finalize_run',
            ),
        ),
    )
    for module, names in method_groups:
        for name in names:
            setattr(cls, name, getattr(module, name))