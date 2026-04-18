import { describe, expect, it } from 'vitest';

import type {
  KnowledgeBase,
  KnowledgeBaseIndexConfigUpdateResponse,
} from '../../services/knowledgeBases';
import {
  applyKnowledgeBaseIndexConfigSuccess,
  applyKnowledgeBaseUpdateSuccess,
} from './useKnowledgeBases';

function createDeferredPromise<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function createKnowledgeBase(id: string): KnowledgeBase {
  return {
    id,
    name: `kb-${id}`,
    description: null,
    tags: null,
    status: 'active',
    readiness: 'ready',
    readiness_updated_at: '2026-04-18T00:00:00Z',
    current_config_version: 1,
    index_config: null,
    created_at: '2026-04-18T00:00:00Z',
    updated_at: '2026-04-18T00:00:00Z',
  };
}

describe('knowledge base mutation success orchestration', () => {
  it('starts independent cache writes together after updating a knowledge base', async () => {
    const calls: string[] = [];
    const detailWrite = createDeferredPromise<void>();
    const selectableWrite = createDeferredPromise<void>();
    const listWrite = createDeferredPromise<void>();

    const done = applyKnowledgeBaseUpdateSuccess(createKnowledgeBase('kb-1'), 'kb-1', {
      invalidate: async () => {
        calls.push('invalidate:start');
      },
      setCachedData: async () => {
        calls.push('detail:start');
        await detailWrite.promise;
        calls.push('detail:end');
        return undefined;
      },
      updateSelectableCollection: async () => {
        calls.push('selectable:start');
        await selectableWrite.promise;
        calls.push('selectable:end');
        return undefined;
      },
      updateListCollections: async () => {
        calls.push('lists:start');
        await listWrite.promise;
        calls.push('lists:end');
        return undefined;
      },
    });

    expect(calls).toEqual(['detail:start', 'selectable:start', 'lists:start']);

    detailWrite.resolve();
    selectableWrite.resolve();
    listWrite.resolve();
    await done;

    expect(calls).toContain('invalidate:start');
  });

  it('starts invalidate and cache writes together after updating index config', async () => {
    const calls: string[] = [];
    const invalidateWrite = createDeferredPromise<void>();
    const detailWrite = createDeferredPromise<void>();
    const rebuildJobWrite = createDeferredPromise<void>();
    const response: KnowledgeBaseIndexConfigUpdateResponse = {
      knowledge_base: createKnowledgeBase('kb-2'),
      rebuild_job: {
        id: 'job-1',
        kb_id: 'kb-2',
        status: 'queued',
        error_message: null,
        stats: null,
        created_at: '2026-04-18T00:00:00Z',
        started_at: null,
        finished_at: null,
      },
    };

    const done = applyKnowledgeBaseIndexConfigSuccess(response, 'kb-2', {
      invalidate: async () => {
        calls.push('invalidate:start');
        await invalidateWrite.promise;
        calls.push('invalidate:end');
      },
      setCachedData: async (key) => {
        if (Array.isArray(key) && key.includes('detail')) {
          calls.push('detail:start');
          await detailWrite.promise;
          calls.push('detail:end');
          return undefined;
        }

        calls.push('rebuild:start');
        await rebuildJobWrite.promise;
        calls.push('rebuild:end');
        return undefined;
      },
    });

    expect(calls).toEqual(['invalidate:start', 'detail:start', 'rebuild:start']);

    invalidateWrite.resolve();
    detailWrite.resolve();
    rebuildJobWrite.resolve();
    await done;
  });
});
