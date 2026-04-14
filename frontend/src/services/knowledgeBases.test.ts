import { describe, expect, it } from 'vitest';

import {
  buildKnowledgeBaseUpdatePayload,
  mergeKnowledgeBaseIntoCollection,
  type KnowledgeBase,
} from './knowledgeBases';

function createKnowledgeBase(overrides?: Partial<KnowledgeBase>): KnowledgeBase {
  return {
    id: 'kb-1',
    name: '原始知识库',
    description: '原始描述',
    tags: ['原标签'],
    status: 'active',
    readiness: 'ready',
    readiness_updated_at: '2026-04-14T00:00:00Z',
    current_config_version: 1,
    index_config: null,
    created_at: '2026-04-14T00:00:00Z',
    updated_at: '2026-04-14T00:00:00Z',
    ...overrides,
  };
}

describe('buildKnowledgeBaseUpdatePayload', () => {
  it('serializes cleared description and tags as explicit null updates', () => {
    expect(
      buildKnowledgeBaseUpdatePayload({
        name: '  更新后的知识库  ',
        description: '   ',
        tagsInput: ' ,  , ',
      })
    ).toEqual({
      name: '更新后的知识库',
      description: null,
      tags: null,
    });
  });

  it('keeps non-empty trimmed description and tags', () => {
    expect(
      buildKnowledgeBaseUpdatePayload({
        name: '  更新后的知识库  ',
        description: '  新描述  ',
        tagsInput: ' API, 教程 ,测试 ',
      })
    ).toEqual({
      name: '更新后的知识库',
      description: '新描述',
      tags: ['API', '教程', '测试'],
    });
  });
});

describe('mergeKnowledgeBaseIntoCollection', () => {
  it('replaces the updated knowledge base so cached names and metadata change immediately', () => {
    const current = [
      createKnowledgeBase(),
      createKnowledgeBase({ id: 'kb-2', name: '第二个知识库' }),
    ];
    const updated = createKnowledgeBase({
      name: '重命名后的知识库',
      description: null,
      tags: null,
    });

    expect(mergeKnowledgeBaseIntoCollection(current, updated)).toEqual([
      updated,
      current[1],
    ]);
  });
});
