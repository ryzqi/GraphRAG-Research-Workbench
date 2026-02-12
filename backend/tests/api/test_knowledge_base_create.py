from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from app.api.v1.endpoints import knowledge_bases as knowledge_bases_endpoint
from app.schemas.knowledge_bases import KnowledgeBaseCreate


def _valid_index_config_payload() -> dict[str, object]:
    return {
        'chunking': {
            'general_strategy': 'query_dependent_multiscale',
            'query_dependent_multiscale': {
                'windows': [
                    {'chunk_size_tokens': 100, 'chunk_overlap_tokens': 20},
                    {'chunk_size_tokens': 200, 'chunk_overlap_tokens': 40},
                ]
            },
        }
    }


def _make_kb_record(*, name: str, index_config: dict[str, object]) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description='desc',
        tags=['alpha'],
        status='active',
        readiness='not_ready',
        readiness_updated_at=now,
        current_config_version=1,
        index_config=index_config,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_knowledge_base_returns_422_when_index_config_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    service = SimpleNamespace(
        get_by_name=AsyncMock(return_value=None),
        create=AsyncMock(),
    )
    monkeypatch.setattr(knowledge_bases_endpoint, 'KnowledgeBaseService', lambda _: service)

    body = KnowledgeBaseCreate.model_validate({'name': 'kb-missing-index-config'})

    with pytest.raises(HTTPException) as exc_info:
        await knowledge_bases_endpoint.create_knowledge_base(db=db, body=body)

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert exc_info.value.detail['code'] == 'INDEX_CONFIG_REQUIRED'
    service.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_knowledge_base_succeeds_when_index_config_is_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    index_config_payload = _valid_index_config_payload()
    persisted_kb = _make_kb_record(name='kb-with-index-config', index_config=index_config_payload)
    service = SimpleNamespace(
        get_by_name=AsyncMock(return_value=None),
        create=AsyncMock(return_value=persisted_kb),
    )
    monkeypatch.setattr(knowledge_bases_endpoint, 'KnowledgeBaseService', lambda _: service)

    body = KnowledgeBaseCreate.model_validate(
        {
            'name': 'kb-with-index-config',
            'description': 'desc',
            'tags': ['alpha'],
            'index_config': index_config_payload,
        }
    )

    result = await knowledge_bases_endpoint.create_knowledge_base(db=db, body=body)

    service.get_by_name.assert_awaited_once_with('kb-with-index-config')
    service.create.assert_awaited_once_with(
        name='kb-with-index-config',
        description='desc',
        tags=['alpha'],
        index_config=body.index_config.model_dump(mode='json'),
    )
    assert result.id == persisted_kb.id
    assert result.status.value == 'active'
    assert result.index_config is not None
    assert result.index_config.chunking.general_strategy.value == 'query_dependent_multiscale'
