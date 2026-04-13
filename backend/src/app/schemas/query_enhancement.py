"""查询增强 / 溯源类型定义（便于 JSON 序列化）。

These structures are shared between agentic graph state and services.
Keep them serializable (plain dict/list/str/bool/int) so LangGraph checkpointing
can persist them safely.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# 注意：需与 KB agentic state 和检索溯源需求保持同步。
QuerySourceKind = Literal[
    # 预处理后的主问题。
    "main",
    # 由规划器确认的释义改写。
    "paraphrase",
    # 拆解得到的子问题。
    "subquery",
    # multi-query 变体。
    "variant",
    # HyDE 生成的假设查询 / 文档。
    "hyde",
    # 重试阶段触发的任意改写 / 变换。
    "rewrite",
    # 兜底或未知来源。
    "other",
]


class QueryRef(TypedDict, total=False):
    """检索 / 评分溯源中引用的查询。"""

    kind: QuerySourceKind
    query: str
    # 对子查询 / 变体，记录其在对应列表中的 0 基索引。
    index: int
    note: str


# 附着在候选项 / 证据上的溯源信息。
QueryHitSource = QueryRef


class QueryItem(QueryRef, total=False):
    """检索层实际使用的查询输入。

    use_dense/use_bm25 allow HyDE or other strategies to affect only one path.
    """

    origin: str
    subquery_id: str
    priority: int
    coverage_tags: list[str]
    purpose: str
    strategy_source: Literal["canonical", "planner_llm", "lexicon", "fallback"]
    trigger_reason: str
    semantic_complete: bool
    preserve_constraints: bool
    retrieval_mode: Literal["hybrid", "dense_only"]
    quality_score: float
    use_dense: bool
    use_bm25: bool
    # 可选的批量 HyDE 载荷；`query` 仍作为主展示项 / 预览项。
    hyde_queries: list[str]
    hyde_aggregation: str
