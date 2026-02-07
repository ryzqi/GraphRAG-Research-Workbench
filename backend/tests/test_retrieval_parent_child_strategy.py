import uuid

import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services.retrieval_service import RetrievalResult, RetrievalService, RetrievedChunk


class _FakeMilvus:
    def __init__(self, parent_contents: dict[str, str] | None = None) -> None:
        self._parent_contents = parent_contents or {}
        self.calls: list[list[str]] = []

    async def query_by_chunk_ids(self, *, chunk_ids: list[str]) -> list[dict]:
        self.calls.append(chunk_ids)
        records: list[dict] = []
        for chunk_id in chunk_ids:
            content = self._parent_contents.get(chunk_id)
            if content is None:
                continue
            records.append(
                {
                    "chunk_id": chunk_id,
                    "kb_id": str(uuid.uuid4()),
                    "material_id": str(uuid.uuid4()),
                    "content": content,
                    "context": "",
                    "chunk_role": "parent",
                    "parent_chunk_id": "",
                    "child_seq": 0,
                    "locator": {},
                    "metadata": {},
                }
            )
        return records


def _build_result(
    *,
    kb_id: uuid.UUID,
    content: str,
    score: float,
    chunk_role: str = "default",
    parent_chunk_id: str | None = None,
) -> RetrievalResult:
    chunk = RetrievedChunk(
        id=uuid.uuid4(),
        kb_id=kb_id,
        material_id=uuid.uuid4(),
        content=content,
        context=None,
        locator=None,
        metadata=None,
        chunk_role=chunk_role,
        parent_chunk_id=parent_chunk_id,
        child_seq=None,
    )
    return RetrievalResult(chunk=chunk, score=score)


@pytest.mark.asyncio
async def test_parent_child_strategy_skips_non_parent_child_chunking() -> None:
    kb_id = uuid.uuid4()
    cfg = IndexConfig.model_validate(
        {
            "chunking": {"general_strategy": "sliding_window"},
            "retrieval": {"parent_child": {"max_parents": 1, "max_children_per_parent": 1}},
        }
    )
    parent_id = str(uuid.uuid4())
    result = _build_result(
        kb_id=kb_id,
        content="child content",
        score=0.9,
        chunk_role="child",
        parent_chunk_id=parent_id,
    )
    milvus = _FakeMilvus(parent_contents={parent_id: "parent content"})
    service = RetrievalService(
        db=None,
        milvus=milvus,
        embedding=object(),
        redis=None,
    )  # type: ignore[arg-type]

    output = await service._apply_parent_child_strategy(
        [result],
        {kb_id: cfg},
        timeout_seconds=5,
    )

    assert len(output) == 1
    assert output[0].context_text == "child content"
    assert milvus.calls == []


@pytest.mark.asyncio
async def test_parent_child_strategy_applies_limits_for_parent_child_chunking() -> None:
    kb_id = uuid.uuid4()
    cfg = IndexConfig.model_validate(
        {
            "chunking": {"general_strategy": "parent_child"},
            "retrieval": {"parent_child": {"max_parents": 1, "max_children_per_parent": 1}},
        }
    )
    parent_a_id = str(uuid.uuid4())
    parent_b_id = str(uuid.uuid4())

    child_a_top = _build_result(
        kb_id=kb_id,
        content="child-a-top",
        score=0.9,
        chunk_role="child",
        parent_chunk_id=parent_a_id,
    )
    child_a_low = _build_result(
        kb_id=kb_id,
        content="child-a-low",
        score=0.8,
        chunk_role="child",
        parent_chunk_id=parent_a_id,
    )
    child_b = _build_result(
        kb_id=kb_id,
        content="child-b",
        score=0.7,
        chunk_role="child",
        parent_chunk_id=parent_b_id,
    )

    milvus = _FakeMilvus(parent_contents={parent_a_id: "parent-a-content"})
    service = RetrievalService(
        db=None,
        milvus=milvus,
        embedding=object(),
        redis=None,
    )  # type: ignore[arg-type]

    output = await service._apply_parent_child_strategy(
        [child_a_top, child_a_low, child_b],
        {kb_id: cfg},
        timeout_seconds=5,
    )

    assert len(output) == 1
    assert output[0].chunk.id == child_a_top.chunk.id
    assert output[0].context_text == "parent-a-content"
    assert milvus.calls == [[parent_a_id]]


@pytest.mark.asyncio
async def test_parent_child_strategy_only_filters_parent_child_kb() -> None:
    parent_child_kb = uuid.uuid4()
    sliding_kb = uuid.uuid4()
    parent_cfg = IndexConfig.model_validate(
        {
            "chunking": {"general_strategy": "parent_child"},
            "retrieval": {"parent_child": {"max_parents": 1, "max_children_per_parent": 1}},
        }
    )
    sliding_cfg = IndexConfig.model_validate({"chunking": {"general_strategy": "sliding_window"}})

    parent_id = str(uuid.uuid4())

    parent_child_hit = _build_result(
        kb_id=parent_child_kb,
        content="child",
        score=0.9,
        chunk_role="child",
        parent_chunk_id=parent_id,
    )
    sliding_hit = _build_result(
        kb_id=sliding_kb,
        content="plain",
        score=0.5,
    )

    milvus = _FakeMilvus(parent_contents={parent_id: "parent-context"})
    service = RetrievalService(
        db=None,
        milvus=milvus,
        embedding=object(),
        redis=None,
    )  # type: ignore[arg-type]

    output = await service._apply_parent_child_strategy(
        [parent_child_hit, sliding_hit],
        {parent_child_kb: parent_cfg, sliding_kb: sliding_cfg},
        timeout_seconds=5,
    )

    assert [r.chunk.id for r in output] == [parent_child_hit.chunk.id, sliding_hit.chunk.id]
    assert output[0].context_text == "parent-context"
    assert output[1].context_text == "plain"
