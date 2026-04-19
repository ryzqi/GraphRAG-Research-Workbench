from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]

_HOT_PATH_FILES = [
    "src/app/integrations/llm_client.py",
    "src/app/services/contextual_embedding_service.py",
    "src/app/services/conversation_summary_service.py",
    "src/app/services/deep_research_runtime.py",
    "src/app/services/general_chat_service_execution.py",
    "src/app/services/general_chat_service_resume_ops.py",
    "src/app/services/general_chat_service_streaming_ops.py",
    "src/app/services/kb_chat_service_execution.py",
    "src/app/services/kb_chat_service_schema.py",
    "src/app/services/query_rewrite_service.py",
    "src/app/agents/kb_chat_agentic/preprocess_context_helpers.py",
    "src/app/agents/kb_chat_agentic/reflection_draft_utils.py",
    "src/app/services/research_planner.py",
]


def test_hot_paths_import_create_chat_model_from_cache_module() -> None:
    missing: list[str] = []
    for relative_path in _HOT_PATH_FILES:
        content = (_BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
        if (
            "from app.integrations.chat_model_cache import" not in content
            or "create_chat_model_cached as create_chat_model" not in content
        ):
            missing.append(relative_path)

    assert missing == [], f"这些热路径还没切到缓存入口: {missing}"


def test_ready_endpoint_exposes_chat_model_cache_stats() -> None:
    content = (
        _BACKEND_ROOT / "src/app/api/v1/endpoints/health.py"
    ).read_text(encoding="utf-8")

    assert "from app.integrations.chat_model_cache import ChatModelCache" in content
    assert 'results["chat_model_cache"] = {' in content
    assert '**ChatModelCache.stats()' in content
    assert '"ok": True' in content
