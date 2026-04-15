"""KB Chat 节点元数据表与派生辅助函数。"""

from __future__ import annotations

from typing import Any

KB_CHAT_NODE_METADATA: dict[str, dict[str, Any]] = {
    "preprocess_subgraph": {"label": "预处理子图", "phase": "preprocess", "order": 0},
    "merge_context": {"label": "上下文合并", "phase": "preprocess", "order": 1},
    "resolve_reference": {"label": "指代消解", "phase": "preprocess", "order": 2},
    "ambiguity_check": {"label": "歧义判断", "phase": "preprocess", "order": 3},
    "query_normalize": {"label": "问题规范", "phase": "preprocess", "order": 4},
    "query_plan": {"label": "查询规划", "phase": "route", "order": 5},
    "decomposition": {"label": "问题拆解", "phase": "enhance", "order": 6},
    "generate_variants": {"label": "多路查询扩展", "phase": "enhance", "order": 7},
    "hyde": {"label": "假设文档扩展", "phase": "enhance", "order": 8},
    "query_plan_finalize": {"label": "查询定稿", "phase": "enhance", "order": 9},
    "preprocess_exit": {"label": "预处理出口", "phase": "enhance", "order": 10},
    "retrieval_subgraph": {"label": "检索子图", "phase": "retrieve", "order": 11},
    "retrieval_plan": {"label": "检索预算规划", "phase": "retrieve", "order": 12},
    "dispatch_subqueries": {"label": "子查询派发", "phase": "retrieve", "order": 13},
    "retrieve_subquery": {"label": "子查询检索", "phase": "retrieve", "order": 14},
    "merge_subquery_context": {
        "label": "子查询上下文合并",
        "phase": "retrieve",
        "order": 15,
    },
    "retrieve": {"label": "知识检索", "phase": "retrieve", "order": 16},
    "context_compress": {"label": "上下文压缩", "phase": "retrieve", "order": 17},
    "transform_query": {"label": "查询改写", "phase": "retrieve", "order": 18},
    "answer_subgraph": {"label": "答案子图", "phase": "generate", "order": 19},
    "draft_generate": {"label": "草稿生成", "phase": "generate", "order": 20},
    "answer_review_dispatch": {"label": "审查分发", "phase": "verify", "order": 21},
    "answer_review_citation": {"label": "引用覆盖审查", "phase": "verify", "order": 22},
    "answer_review": {"label": "回答有效性审查", "phase": "verify", "order": 23},
    "answer_review_fuse": {"label": "审查结果融合", "phase": "verify", "order": 24},
    "answer_repair": {"label": "答案修复", "phase": "verify", "order": 25},
    "answer_commit": {"label": "答案提交", "phase": "generate", "order": 26},
    "force_exit": {"label": "提前终止", "phase": "finalize", "order": 27},
    "semantic_cache": {"label": "语义缓存", "phase": "finalize", "order": 28},
}


def resolve_kb_chat_node_metadata(node_id: str) -> dict[str, Any]:
    metadata = KB_CHAT_NODE_METADATA.get(node_id)
    if metadata:
        return dict(metadata)
    return {"label": node_id, "phase": None, "order": None}


def extend_kb_chat_node_metadata(node_id: str, **extras: Any) -> dict[str, Any]:
    metadata = resolve_kb_chat_node_metadata(node_id)
    metadata.update(extras)
    return metadata


def resolve_kb_chat_node_label(node_name: str | None) -> str | None:
    if not isinstance(node_name, str) or not node_name.strip():
        return None
    metadata = KB_CHAT_NODE_METADATA.get(node_name.strip())
    if not isinstance(metadata, dict):
        return None
    label = metadata.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else None
