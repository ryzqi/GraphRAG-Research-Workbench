from app.services import deep_research_runtime as dr


def test_build_workspace_context_files_is_cached():
    builder = dr._build_workspace_context_files
    cache_clear = getattr(builder, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()

    first = builder()
    second = builder()

    assert first is second

    cache_info = getattr(builder, "cache_info", None)
    assert callable(cache_info)
    info = cache_info()
    assert info.hits >= 1
    assert info.misses == 1
