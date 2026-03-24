from __future__ import annotations

import asyncio
from types import SimpleNamespace
import uuid

import pytest

from app.agents.tools.kb_retrieve import (
    build_kb_retrieve_tool,
    push_kb_invocation_request_id,
    reset_kb_invocation_request_id,
)
from app.integrations.milvus_client import MilvusSearchHit
from app.schemas.knowledge_bases import ChunkingStrategy
from app.services.retrieval_service import RetrievalResult, RetrievalService, RetrievedChunk


class _FakeMilvus:
    def __init__(self, hit: MilvusSearchHit) -> None:
        self._hit = hit
        self.hybrid_calls: list[dict[str, object]] = []
        self.sparse_calls: list[dict[str, object]] = []

    async def hybrid_search(self, **kwargs: object) -> list[MilvusSearchHit]:
        self.hybrid_calls.append(dict(kwargs))
        return []

    async def sparse_search(self, **kwargs: object) -> list[MilvusSearchHit]:
        self.sparse_calls.append(dict(kwargs))
        return [self._hit]


@pytest.mark.asyncio
async def test_retrieve_layer_falls_back_to_sparse_when_embedding_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    hit = MilvusSearchHit(
        chunk_id=str(chunk_id),
        kb_id=str(kb_id),
        material_id=str(material_id),
        score=0.91,
        content="CoT 适合单路径、步骤明确的推理任务。",
        context="CoT 适合单路径、步骤明确的推理任务。",
        locator={"citation_label": "Agent基础"},
        metadata={"source": "test"},
    )
    milvus = _FakeMilvus(hit)
    service = RetrievalService(
        db=None,
        milvus=milvus,
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )

    async def _timeout_embedding(*args: object, **kwargs: object) -> object:
        raise asyncio.TimeoutError()

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    async def _return_results(results: object, *args: object, **kwargs: object) -> object:
        return results

    async def _skip_semantic_dedupe(*args: object, **kwargs: object) -> tuple[object, int, str]:
        return args[0], 0, "not_needed"

    async def _skip_rerank(
        query: str,
        results: list[object],
        top_k: int,
        *args: object,
        **kwargs: object,
    ) -> tuple[list[object], bool, str, None]:
        _ = query, args, kwargs
        return results[:top_k], False, "disabled_for_test", None

    monkeypatch.setattr(service, "_resolve_query_embedding", _timeout_embedding)
    monkeypatch.setattr(service, "_hydrate_chunks_from_postgres", _noop)
    monkeypatch.setattr(service, "_apply_parent_child_strategy", _return_results)
    monkeypatch.setattr(service, "_apply_query_dependent_multiscale_strategy", _return_results)
    monkeypatch.setattr(service, "_ensure_chunk_citation_labels", _noop)
    monkeypatch.setattr(service, "_dedupe_by_semantic_similarity", _skip_semantic_dedupe)
    monkeypatch.setattr(service, "_maybe_rerank", _skip_rerank)

    draft = await service.retrieve_layer(
        query_items=[
            {
                "kind": "main",
                "query": "CoT 适合什么场景？",
                "index": 0,
                "use_dense": True,
                "use_bm25": True,
            }
        ],
        kb_ids=[kb_id],
        top_n=1,
        per_query_top_k=1,
        global_candidates_limit=1,
        rerank_input_limit=1,
    )

    assert milvus.hybrid_calls == []
    assert len(milvus.sparse_calls) == 1
    assert draft.results
    assert draft.results[0].chunk.id == chunk_id
    assert draft.evidence_items[0]["chunk_id"] == str(chunk_id)
    assert draft.reranked_candidates[0]["chunk_id"] == str(chunk_id)


@pytest.mark.asyncio
async def test_expand_direct_section_neighbors_adds_following_same_section_chunks() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    seed_chunk_id = uuid.uuid4()
    memory_chunk_id = uuid.uuid4()
    action_chunk_id = uuid.uuid4()

    class _FakeResult:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        def all(self) -> list[SimpleNamespace]:
            return self._rows

    class _FakeDb:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        async def execute(self, stmt: object) -> _FakeResult:
            _ = stmt
            return _FakeResult(self._rows)

    db = _FakeDb(
        [
            SimpleNamespace(
                id=seed_chunk_id,
                kb_id=kb_id,
                material_id=material_id,
                raw_text="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
                locator={"citation_label": "Agent基础"},
                chunk_index=19,
                heading_path="AI Agent 的六大核心组件",
                global_chunk_order=19,
            ),
            SimpleNamespace(
                id=memory_chunk_id,
                kb_id=kb_id,
                material_id=material_id,
                raw_text="### 2.2 记忆 (Memory)\n负责存储上下文与长期经验。",
                locator={"citation_label": "Agent基础"},
                chunk_index=20,
                heading_path="AI Agent 的六大核心组件 > 记忆",
                global_chunk_order=20,
            ),
            SimpleNamespace(
                id=action_chunk_id,
                kb_id=kb_id,
                material_id=material_id,
                raw_text="### 2.6 行动 (Action)\n负责执行最终操作。",
                locator={"citation_label": "Agent基础"},
                chunk_index=24,
                heading_path="AI Agent 的六大核心组件 > 行动",
                global_chunk_order=24,
            ),
        ]
    )
    service = RetrievalService(
        db=db,
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )

    seed_chunk = RetrievedChunk(
        id=seed_chunk_id,
        kb_id=kb_id,
        material_id=material_id,
        content="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
        context=None,
        locator={"citation_label": "Agent基础"},
        metadata=None,
        chunk_role="default",
        parent_chunk_id=None,
        child_seq=None,
        chunk_index=19,
        heading_path="AI Agent 的六大核心组件",
        global_chunk_order=19,
    )
    expanded = await service._expand_direct_section_neighbors(
        [RetrievalResult(chunk=seed_chunk, score=0.91)],
        query_items=[{"kind": "main", "query": "AI Agent 的六大核心组件是什么？"}],
        top_n=6,
        timeout_seconds=None,
    )

    texts = [row.chunk.content for row in expanded]
    assert any("### 2.2 记忆 (Memory)" in text for text in texts)
    assert any("### 2.6 行动 (Action)" in text for text in texts)


@pytest.mark.asyncio
async def test_expand_direct_section_neighbors_coalesces_seed_content_until_section_boundary() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    seed_chunk_id = uuid.uuid4()

    class _FakeResult:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        def all(self) -> list[SimpleNamespace]:
            return self._rows

    class _FakeDb:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        async def execute(self, stmt: object) -> _FakeResult:
            _ = stmt
            return _FakeResult(self._rows)

    rows = [
        SimpleNamespace(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
            locator={"citation_label": "Agent基础"},
            chunk_index=19,
            heading_path="AI Agent 的六大核心组件",
            global_chunk_order=19,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.2 记忆 (Memory)\n负责存储上下文与长期经验。",
            locator={"citation_label": "Agent基础"},
            chunk_index=20,
            heading_path="AI Agent 的六大核心组件 > 记忆",
            global_chunk_order=20,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.3 规划 (Planning)\n负责拆解任务与安排步骤。",
            locator={"citation_label": "Agent基础"},
            chunk_index=21,
            heading_path="AI Agent 的六大核心组件 > 规划",
            global_chunk_order=21,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.4 推理引擎 (Reasoning Engine)\n负责分析与决策。",
            locator={"citation_label": "Agent基础"},
            chunk_index=22,
            heading_path="AI Agent 的六大核心组件 > 推理引擎",
            global_chunk_order=22,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.5 工具使用 (Tool Use)\n负责调用外部工具。",
            locator={"citation_label": "Agent基础"},
            chunk_index=23,
            heading_path="AI Agent 的六大核心组件 > 工具使用",
            global_chunk_order=23,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.6 行动 (Action)\n负责执行最终操作。",
            locator={"citation_label": "Agent基础"},
            chunk_index=24,
            heading_path="AI Agent 的六大核心组件 > 行动",
            global_chunk_order=24,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 3. 六大组件协同工作流程\n这里不应再被拼接进上一节。",
            locator={"citation_label": "Agent基础"},
            chunk_index=25,
            heading_path="六大组件协同工作流程",
            global_chunk_order=25,
        ),
    ]
    service = RetrievalService(
        db=_FakeDb(rows),
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )
    seed_chunk = RetrievedChunk(
        id=seed_chunk_id,
        kb_id=kb_id,
        material_id=material_id,
        content="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
        context=None,
        locator={"citation_label": "Agent基础"},
        metadata=None,
        chunk_role="default",
        parent_chunk_id=None,
        child_seq=None,
        chunk_index=19,
        heading_path="AI Agent 的六大核心组件",
        global_chunk_order=19,
    )

    expanded = await service._expand_direct_section_neighbors(
        [RetrievalResult(chunk=seed_chunk, score=0.91)],
        query_items=[{"kind": "main", "query": "AI Agent 的六大核心组件是什么？"}],
        top_n=6,
        timeout_seconds=None,
    )

    assert expanded[0].chunk.content == seed_chunk.content
    assert expanded[0].context_text is not None
    assert "### 2.2 记忆 (Memory)" in expanded[0].context_text
    assert "### 2.5 工具使用 (Tool Use)" in expanded[0].context_text
    assert "### 2.6 行动 (Action)" in expanded[0].context_text
    assert "## 3. 六大组件协同工作流程" not in expanded[0].context_text
    assert "### 2.5 工具使用 (Tool Use)" in RetrievalService._result_excerpt(expanded[0])


@pytest.mark.asyncio
async def test_expand_direct_section_neighbors_still_coalesces_seed_context_when_candidate_count_already_exceeds_top_n() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    seed_chunk_id = uuid.uuid4()

    class _FakeResult:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        def all(self) -> list[SimpleNamespace]:
            return self._rows

    class _FakeDb:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        async def execute(self, stmt: object) -> _FakeResult:
            _ = stmt
            return _FakeResult(self._rows)

    rows = [
        SimpleNamespace(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
            locator={"citation_label": "Agent基础"},
            chunk_index=19,
            heading_path="AI Agent 的六大核心组件",
            global_chunk_order=19,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.2 记忆 (Memory)\n负责存储上下文与长期经验。",
            locator={"citation_label": "Agent基础"},
            chunk_index=20,
            heading_path="AI Agent 的六大核心组件 > 记忆",
            global_chunk_order=20,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.3 规划 (Planning)\n负责拆解任务与安排步骤。",
            locator={"citation_label": "Agent基础"},
            chunk_index=21,
            heading_path="AI Agent 的六大核心组件 > 规划",
            global_chunk_order=21,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.4 推理引擎 (Reasoning Engine)\n负责分析与决策。",
            locator={"citation_label": "Agent基础"},
            chunk_index=22,
            heading_path="AI Agent 的六大核心组件 > 推理引擎",
            global_chunk_order=22,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.5 工具使用 (Tool Use)\n负责调用外部工具。",
            locator={"citation_label": "Agent基础"},
            chunk_index=23,
            heading_path="AI Agent 的六大核心组件 > 工具使用",
            global_chunk_order=23,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.6 行动 (Action)\n负责执行最终操作。",
            locator={"citation_label": "Agent基础"},
            chunk_index=24,
            heading_path="AI Agent 的六大核心组件 > 行动",
            global_chunk_order=24,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 3. 六大组件协同工作流程\n这里不应再被拼接进上一节。",
            locator={"citation_label": "Agent基础"},
            chunk_index=25,
            heading_path="六大组件协同工作流程",
            global_chunk_order=25,
        ),
    ]
    service = RetrievalService(
        db=_FakeDb(rows),
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )
    seed_chunk = RetrievedChunk(
        id=seed_chunk_id,
        kb_id=kb_id,
        material_id=material_id,
        content="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
        context=None,
        locator={"citation_label": "Agent基础"},
        metadata=None,
        chunk_role="default",
        parent_chunk_id=None,
        child_seq=None,
        chunk_index=19,
        heading_path="AI Agent 的六大核心组件",
        global_chunk_order=19,
    )
    filler_results = [
        RetrievalResult(
            chunk=RetrievedChunk(
                id=uuid.uuid4(),
                kb_id=kb_id,
                material_id=material_id,
                content=f"无关候选 {index}",
                context=None,
                locator={"citation_label": f"Filler-{index}"},
                metadata=None,
                chunk_role="default",
                parent_chunk_id=None,
                child_seq=None,
                chunk_index=100 + index,
                heading_path=f"其他章节 > {index}",
                global_chunk_order=100 + index,
            ),
            score=0.9 - index * 0.001,
        )
        for index in range(1, 12)
    ]

    expanded = await service._expand_direct_section_neighbors(
        [RetrievalResult(chunk=seed_chunk, score=0.91), *filler_results],
        query_items=[{"kind": "main", "query": "AI Agent 的六大核心组件是什么？"}],
        top_n=6,
        timeout_seconds=None,
    )

    assert len(expanded) == 12
    assert expanded[0].context_text is not None
    assert "### 2.2 记忆 (Memory)" in expanded[0].context_text
    assert "### 2.6 行动 (Action)" in expanded[0].context_text
    assert "## 3. 六大组件协同工作流程" not in expanded[0].context_text
    assert "### 2.5 工具使用 (Tool Use)" in RetrievalService._result_excerpt(expanded[0])


@pytest.mark.asyncio
async def test_apply_parent_child_strategy_preserves_preexpanded_context_for_non_parent_child_kb() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    seed_chunk_id = uuid.uuid4()

    class _FakeResult:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        def all(self) -> list[SimpleNamespace]:
            return self._rows

    class _FakeDb:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        async def execute(self, stmt: object) -> _FakeResult:
            _ = stmt
            return _FakeResult(self._rows)

    rows = [
        SimpleNamespace(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
            locator={"citation_label": "Agent基础"},
            chunk_index=19,
            heading_path="AI Agent 的六大核心组件",
            global_chunk_order=19,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.2 记忆 (Memory)\n负责存储上下文与长期经验。",
            locator={"citation_label": "Agent基础"},
            chunk_index=20,
            heading_path="AI Agent 的六大核心组件 > 记忆",
            global_chunk_order=20,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.5 工具使用 (Tool Use)\n负责调用外部工具。",
            locator={"citation_label": "Agent基础"},
            chunk_index=23,
            heading_path="AI Agent 的六大核心组件 > 工具使用",
            global_chunk_order=23,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="### 2.6 行动 (Action)\n负责执行最终操作。",
            locator={"citation_label": "Agent基础"},
            chunk_index=24,
            heading_path="AI Agent 的六大核心组件 > 行动",
            global_chunk_order=24,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 3. 六大组件协同工作流程\n这里不应再被拼接进上一节。",
            locator={"citation_label": "Agent基础"},
            chunk_index=25,
            heading_path="六大组件协同工作流程",
            global_chunk_order=25,
        ),
    ]
    service = RetrievalService(
        db=_FakeDb(rows),
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )
    seed_chunk = RetrievedChunk(
        id=seed_chunk_id,
        kb_id=kb_id,
        material_id=material_id,
        content="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)\n负责获取信息。",
        context=None,
        locator={"citation_label": "Agent基础"},
        metadata=None,
        chunk_role="default",
        parent_chunk_id=None,
        child_seq=None,
        chunk_index=19,
        heading_path="AI Agent 的六大核心组件",
        global_chunk_order=19,
    )

    expanded = await service._expand_direct_section_neighbors(
        [RetrievalResult(chunk=seed_chunk, score=0.91)],
        query_items=[{"kind": "main", "query": "AI Agent 的六大核心组件是什么？"}],
        top_n=6,
        timeout_seconds=None,
    )

    assert expanded[0].context_text is not None
    assert "### 2.5 工具使用 (Tool Use)" in expanded[0].context_text

    preserved = await service._apply_parent_child_strategy(
        expanded,
        {
            kb_id: SimpleNamespace(
                chunking=SimpleNamespace(
                    general_strategy=ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
                )
            )
        },
        max_parents=8,
        max_children_per_parent=3,
        timeout_seconds=None,
    )

    assert preserved[0].context_text is not None
    assert "### 2.5 工具使用 (Tool Use)" in preserved[0].context_text
    assert "### 2.6 行动 (Action)" in preserved[0].context_text
    assert "## 3. 六大组件协同工作流程" not in preserved[0].context_text


@pytest.mark.asyncio
async def test_populate_result_context_from_heading_path_recovers_mid_section_architecture_header() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    header_chunk_id = uuid.uuid4()
    seed_chunk_id = uuid.uuid4()
    challenge_chunk_id = uuid.uuid4()
    next_section_chunk_id = uuid.uuid4()
    heading_path = "一. Embedding 模型和 Rerank 模型 > 3. Re-rank模型：深度匹配与精准排序的“裁判” > 技术架构：交叉编码器"

    class _FakeResult:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        def all(self) -> list[SimpleNamespace]:
            return self._rows

    class _FakeDb:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        async def execute(self, stmt: object) -> _FakeResult:
            _ = stmt
            return _FakeResult(self._rows)

    rows = [
        SimpleNamespace(
            id=header_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text=(
                "- **技术架构：交叉编码器 (Cross-Encoder)**\n"
                "    - 将“用户查询”和“单个候选项”作为一个整体输入到模型中。"
            ),
            locator={"citation_label": "Agent基础"},
            chunk_index=8,
            heading_path=heading_path,
            global_chunk_order=8,
        ),
        SimpleNamespace(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text=(
                "和“单个候选项”作为一个整体输入到模型中，进行深度的语义交互和匹配分析。\n"
                "这种方式能更充分地理解查询与候选项之间的细微关联。"
            ),
            locator={"citation_label": "Agent基础"},
            chunk_index=9,
            heading_path=heading_path,
            global_chunk_order=9,
        ),
        SimpleNamespace(
            id=challenge_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text=(
                "- **面临的挑战：算力与性能的平衡**\n"
                "    - 需要在排序效果与系统实时响应之间取得平衡。"
            ),
            locator={"citation_label": "Agent基础"},
            chunk_index=10,
            heading_path=heading_path,
            global_chunk_order=10,
        ),
        SimpleNamespace(
            id=next_section_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text="## 4. 协同工作实例：搜索“亲子互动游戏”",
            locator={"citation_label": "Agent基础"},
            chunk_index=11,
            heading_path="一. Embedding 模型和 Rerank 模型 > 4. 协同工作实例",
            global_chunk_order=11,
        ),
    ]

    service = RetrievalService(
        db=_FakeDb(rows),
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )
    seed_result = RetrievalResult(
        chunk=RetrievedChunk(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            content=rows[1].raw_text,
            context=None,
            locator={"citation_label": "Agent基础"},
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
            chunk_index=9,
            heading_path=heading_path,
            global_chunk_order=9,
        ),
        score=0.95,
    )

    enriched = await service._populate_result_context_from_heading_path(
        seed_result,
        timeout_seconds=None,
    )

    assert enriched.context_text is not None
    assert "Cross-Encoder" in enriched.context_text
    assert "算力与性能的平衡" in enriched.context_text
    assert "## 4. 协同工作实例" not in enriched.context_text
    assert "Cross-Encoder" in RetrievalService._result_excerpt(enriched)


@pytest.mark.asyncio
async def test_populate_result_context_recovers_architecture_header_without_heading_path() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    header_chunk_id = uuid.uuid4()
    seed_chunk_id = uuid.uuid4()
    next_section_chunk_id = uuid.uuid4()

    class _FakeResult:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        def all(self) -> list[SimpleNamespace]:
            return self._rows

    class _FakeDb:
        def __init__(self, rows: list[SimpleNamespace]) -> None:
            self._rows = rows

        async def execute(self, stmt: object) -> _FakeResult:
            _ = stmt
            return _FakeResult(self._rows)

    rows = [
        SimpleNamespace(
            id=header_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text=(
                "对于没有历史点击数据的新商品，模型难以准确生成其向量。\n"
                "---\n"
                "## 3. Re-rank模型：深度匹配与精准排序的“裁判”\n\n"
                "- **技术架构：交叉编码器 (Cross-Encoder)**\n"
                "    - 将“用户查询”和“单个候选项”作为一个整体输入到模型中。"
            ),
            locator={"citation_label": "Agent基础"},
            chunk_index=8,
            heading_path=None,
            global_chunk_order=8,
        ),
        SimpleNamespace(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text=(
                "和“单个候选项”作为一个整体输入到模型中，进行深度的语义交互和匹配分析。\n"
                "- **面临的挑战：算力与性能的平衡**"
            ),
            locator={"citation_label": "Agent基础"},
            chunk_index=9,
            heading_path=None,
            global_chunk_order=9,
        ),
        SimpleNamespace(
            id=next_section_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            raw_text=(
                "不同复杂度的 Re-rank 模型协同工作。\n"
                "---\n"
                "## 4. 协同工作实例：搜索“亲子互动游戏”"
            ),
            locator={"citation_label": "Agent基础"},
            chunk_index=10,
            heading_path=None,
            global_chunk_order=10,
        ),
    ]

    service = RetrievalService(
        db=_FakeDb(rows),
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )
    seed_result = RetrievalResult(
        chunk=RetrievedChunk(
            id=seed_chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            content=rows[1].raw_text,
            context=None,
            locator={"citation_label": "Agent基础"},
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
            chunk_index=9,
            heading_path=None,
            global_chunk_order=9,
        ),
        score=0.95,
    )

    enriched = await service._populate_result_context_from_heading_path(
        seed_result,
        timeout_seconds=None,
    )

    assert enriched.context_text is not None
    assert "## 3. Re-rank模型" in enriched.context_text
    assert "Cross-Encoder" in enriched.context_text
    assert "算力与性能的平衡" in enriched.context_text
    assert "## 4. 协同工作实例" not in enriched.context_text
    assert "Cross-Encoder" in RetrievalService._result_excerpt(enriched)


@pytest.mark.asyncio
async def test_maybe_rerank_prefers_context_text_over_chunk_content() -> None:
    class _RecordingReranker:
        def __init__(self) -> None:
            self.documents: list[str] = []

        async def rerank(
            self,
            *,
            query: str,
            documents: list[str],
            top_n: int,
            timeout_seconds: float | None = None,
        ) -> list[SimpleNamespace]:
            _ = query, top_n, timeout_seconds
            self.documents = list(documents)
            return [SimpleNamespace(index=0, score=0.99)]

    reranker = _RecordingReranker()
    service = RetrievalService(
        db=None,
        milvus=SimpleNamespace(),
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=reranker,
    )
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    merged_section = "\n".join(
        [
            "## 2. AI Agent 的六大核心组件",
            "### 2.1 感知 (Perception)",
            "### 2.2 记忆 (Memory)",
            "### 2.3 规划 (Planning)",
            "### 2.4 推理引擎 (Reasoning Engine)",
            "### 2.5 工具使用 (Tool Use)",
            "### 2.6 行动 (Action)",
        ]
    )
    results = [
        RetrievalResult(
            chunk=RetrievedChunk(
                id=chunk_id,
                kb_id=kb_id,
                material_id=material_id,
                content="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)",
                context=None,
                locator={"citation_label": "Agent基础"},
                metadata=None,
                chunk_role="default",
                parent_chunk_id=None,
                child_seq=None,
            ),
            score=0.91,
            context_text=merged_section,
        )
    ]

    ordered, applied, reason, latency_ms = await service._maybe_rerank(
        "AI Agent 的六大核心组件是什么？",
        results,
        top_k=1,
        enabled=True,
    )

    assert applied is True
    assert reason is None
    assert latency_ms is not None
    assert ordered
    assert reranker.documents == [merged_section]


@pytest.mark.asyncio
async def test_kb_retrieve_tool_keeps_full_context_excerpt_for_coalesced_section() -> None:
    class _FakeContextBuilder:
        def build_retrieval_context(
            self, results: list[RetrievalResult]
        ) -> tuple[str, list[RetrievalResult], dict[str, int], dict[str, int | bool]]:
            text = "\n\n".join(r.context_text or r.chunk.content for r in results)
            return text, results, {"tokens": 0, "chars": len(text), "items": len(results)}, {
                "truncated": False,
                "dropped_items": 0,
                "dropped_tokens": 0,
            }

    class _FakeLayer:
        def __init__(self, results: list[RetrievalResult]) -> None:
            self.results = results
            self.evidence_items: list[dict[str, object]] = []

    class _FakeRetrieval:
        def __init__(self, results: list[RetrievalResult]) -> None:
            self.last_layer_draft = _FakeLayer(results)

        async def retrieve_layer(self, **kwargs: object) -> _FakeLayer:
            _ = kwargs
            return self.last_layer_draft

    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    long_section = "\n".join(
        [
            "## 2. AI Agent 的六大核心组件",
            "### 2.1 感知 (Perception) " + "负责获取信息。" * 40,
            "### 2.2 记忆 (Memory) " + "负责存储上下文。" * 20,
            "### 2.3 规划 (Planning) " + "负责拆解任务。" * 20,
            "### 2.4 推理引擎 (Reasoning Engine) " + "负责分析与决策。" * 20,
            "### 2.5 工具使用 (Tool Use) " + "负责调用外部工具。" * 20,
            "### 2.6 行动 (Action) " + "负责执行最终操作。" * 20,
        ]
    )
    result = RetrievalResult(
        chunk=RetrievedChunk(
            id=chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            content="## 2. AI Agent 的六大核心组件\n### 2.1 感知 (Perception)",
            context=None,
            locator={"filename": "Agent基础.md", "citation_label": "Agent基础"},
            metadata=None,
            chunk_role="default",
            parent_chunk_id=None,
            child_seq=None,
        ),
        score=0.95,
        context_text=long_section,
    )
    tool = build_kb_retrieve_tool(
        retrieval=_FakeRetrieval([result]),  # type: ignore[arg-type]
        default_kb_ids=[kb_id],
        retrieval_overrides={},
        context_builder=_FakeContextBuilder(),
    )

    token = push_kb_invocation_request_id("test-request")
    try:
        await tool.ainvoke(
            {
                "query": "AI Agent 的六大核心组件是什么？",
                "kb_ids": [str(kb_id)],
                "top_k": 1,
                "query_items": [
                    {
                        "kind": "main",
                        "query": "AI Agent 的六大核心组件是什么？",
                        "use_dense": True,
                        "use_bm25": True,
                    }
                ],
                "per_query_top_k": 3,
                "global_candidates_limit": 10,
                "rerank_input_limit": 5,
                "retrieval_round": 0,
            }
        )
    finally:
        reset_kb_invocation_request_id(token)

    store = getattr(tool, "_kb_invocation_meta_by_request_id")
    invocation_meta = store.get("test-request")
    assert invocation_meta is not None
    excerpt = invocation_meta["evidence_items"][0]["excerpt"]
    assert "### 2.6 行动 (Action)" in excerpt


@pytest.mark.asyncio
async def test_retrieve_layer_serializes_shared_db_session_access_for_parallel_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    class _FakeDbResult:
        def __init__(self, rows: list[tuple[uuid.UUID, dict[str, object]]]) -> None:
            self._rows = rows

        def all(self) -> list[tuple[uuid.UUID, dict[str, object]]]:
            return self._rows

    class _BusyDb:
        def __init__(self) -> None:
            self._busy = False
            self._call_count = 0

        async def execute(self, stmt: object) -> _FakeDbResult:
            _ = stmt
            if self._busy:
                raise RuntimeError("concurrent db execute")
            self._busy = True
            self._call_count += 1
            try:
                await asyncio.sleep(0.02)
                if self._call_count % 2 == 1:
                    return _FakeDbResult([])
                return _FakeDbResult([(kb_id, {})])
            finally:
                self._busy = False

    class _FakeMilvus:
        async def hybrid_search(self, **kwargs: object) -> list[MilvusSearchHit]:
            _ = kwargs
            return [
                MilvusSearchHit(
                    chunk_id=str(chunk_id),
                    kb_id=str(kb_id),
                    material_id=str(material_id),
                    score=0.91,
                    content="Re-rank 模型的核心任务是排序。",
                    context="Re-rank 模型的核心任务是排序。",
                    locator={"citation_label": "Agent基础"},
                    metadata={"source": "test"},
                )
            ]

    service = RetrievalService(
        db=_BusyDb(),  # type: ignore[arg-type]
        milvus=_FakeMilvus(),  # type: ignore[arg-type]
        embedding=SimpleNamespace(),
        redis=None,
        query_rewriter=None,
        reranker=None,
    )

    async def _fake_embedding(
        item: object,
        *args: object,
        **kwargs: object,
    ) -> tuple[list[float], int, int, str]:
        _ = item, args, kwargs
        return [0.1, 0.2, 0.3], 0, 0, "test"

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    async def _return_results(results: object, *args: object, **kwargs: object) -> object:
        _ = args, kwargs
        return results

    async def _skip_semantic_dedupe(*args: object, **kwargs: object) -> tuple[object, int, str]:
        _ = kwargs
        return args[0], 0, "not_needed"

    async def _skip_rerank(
        query: str,
        results: list[object],
        top_k: int,
        *args: object,
        **kwargs: object,
    ) -> tuple[list[object], bool, str, None]:
        _ = query, args, kwargs
        return results[:top_k], False, "disabled_for_test", None

    monkeypatch.setattr(service, "_resolve_query_embedding", _fake_embedding)
    monkeypatch.setattr(service, "_hydrate_chunks_from_postgres", _noop)
    monkeypatch.setattr(service, "_expand_direct_section_neighbors", _return_results)
    monkeypatch.setattr(service, "_apply_parent_child_strategy", _return_results)
    monkeypatch.setattr(service, "_apply_query_dependent_multiscale_strategy", _return_results)
    monkeypatch.setattr(service, "_ensure_chunk_citation_labels", _noop)
    monkeypatch.setattr(service, "_dedupe_by_semantic_similarity", _skip_semantic_dedupe)
    monkeypatch.setattr(service, "_maybe_rerank", _skip_rerank)

    async def _call_once() -> RetrievalResult | None:
        draft = await service.retrieve_layer(
            query_items=[
                {
                    "kind": "main",
                    "query": "Re-rank 模型负责什么？",
                    "index": 0,
                    "use_dense": True,
                    "use_bm25": True,
                }
            ],
            kb_ids=[kb_id],
            top_n=1,
            per_query_top_k=1,
            global_candidates_limit=1,
            rerank_input_limit=1,
        )
        return draft.results[0] if draft.results else None

    results = await asyncio.gather(_call_once(), _call_once(), return_exceptions=True)

    assert all(not isinstance(item, Exception) for item in results)
    assert all(item is not None for item in results)
