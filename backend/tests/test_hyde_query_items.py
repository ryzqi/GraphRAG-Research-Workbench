from app.services.query_rewrite_service import HYDE_AGGREGATION, build_query_items


def test_build_query_items_includes_hyde_batch_payload() -> None:
    items = build_query_items(
        main_query="主查询",
        hyde_docs=[" 假设文档A ", "假设文档B", "假设文档A"],
        hyde_note="retry_regenerated",
    )

    hyde_item = next(item for item in items if item.get("kind") == "hyde")
    assert hyde_item["query"] == "假设文档A"
    assert hyde_item["hyde_queries"] == ["假设文档A", "假设文档B"]
    assert hyde_item["hyde_aggregation"] == HYDE_AGGREGATION
    assert hyde_item["note"] == "retry_regenerated"
    assert hyde_item["use_dense"] is True
    assert hyde_item["use_bm25"] is False


def test_build_query_items_keeps_backward_compat_with_single_hyde_doc() -> None:
    items = build_query_items(main_query="主查询", hyde_doc=" 单条假设文档 ")

    hyde_item = next(item for item in items if item.get("kind") == "hyde")
    assert hyde_item["query"] == "单条假设文档"
    assert hyde_item["hyde_queries"] == ["单条假设文档"]
