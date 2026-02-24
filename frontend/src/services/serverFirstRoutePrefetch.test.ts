import { describe, expect, it, vi } from 'vitest';
import { unstable_serialize } from 'swr';
import {
  prefetchGeneralChatRouteData,
  prefetchKbChatRouteData,
  prefetchKnowledgeBaseAddDocumentsRouteData,
  prefetchKnowledgeBaseDetailRouteData,
} from './serverFirstRoutePrefetch';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('serverFirstRoutePrefetch', () => {
  it('starts kb-chat first-screen requests in parallel', async () => {
    const recentDeferred = deferred<any>();
    const selectableDeferred = deferred<any>();
    const getRecentChatsFn = vi.fn(() => recentDeferred.promise);
    const listSelectableKnowledgeBasesFn = vi.fn(() => selectableDeferred.promise);

    const task = prefetchKbChatRouteData({ getRecentChatsFn, listSelectableKnowledgeBasesFn });

    expect(getRecentChatsFn).toHaveBeenCalledTimes(1);
    expect(listSelectableKnowledgeBasesFn).toHaveBeenCalledTimes(1);

    recentDeferred.resolve({
      items: [],
      web_search_available: true,
    });
    selectableDeferred.resolve({ items: [] });

    const fallback = await task;
    expect(fallback[unstable_serialize(['chats', 'recent', 20])]).toBeDefined();
    expect(fallback[unstable_serialize(['knowledgeBases', 'selectable'])]).toEqual([]);
  });

  it('preloads detail route data with route-layer cache keys', async () => {
    const kbId = 'kb-1';
    const fallback = await prefetchKnowledgeBaseDetailRouteData(kbId, {
      getKnowledgeBaseFn: vi.fn(async () => ({ id: kbId } as any)),
      getKnowledgeBaseIngestionStateFn: vi.fn(
        async () => ({ kb_id: kbId, has_active_batch: false } as any)
      ),
      getLatestIngestionBatchFn: vi.fn(async () => ({ id: 'batch-1' } as any)),
    });

    expect(fallback[unstable_serialize(['knowledgeBases', 'detail', kbId])]).toEqual({ id: kbId });
    expect(fallback[unstable_serialize(['knowledgeBases', 'ingestionState', kbId])]).toEqual({
      kb_id: kbId,
      has_active_batch: false,
    });
    expect(fallback[unstable_serialize(['ingestionBatches', 'latest', kbId])]).toEqual({
      id: 'batch-1',
    });
  });

  it('does not request bootstrap job when jobId is absent', async () => {
    const getBootstrapSubmissionFn = vi.fn(async () => ({ id: 'job-1' }));

    await prefetchKnowledgeBaseAddDocumentsRouteData('kb-1', undefined, {
      getKnowledgeBaseFn: vi.fn(async () => ({ id: 'kb-1' } as any)),
      getLatestIngestionBatchFn: vi.fn(async () => ({ id: 'batch-1' } as any)),
      getBootstrapSubmissionFn,
    });

    expect(getBootstrapSubmissionFn).not.toHaveBeenCalled();
  });

  it('normalizes general chat recent history fallback format', async () => {
    const fallback = await prefetchGeneralChatRouteData({
      getRecentChatsFn: vi.fn(async () => ({
        items: [
          {
            id: 's-1',
            title: null,
            session_type: 'general_chat',
            updated_at: '2026-02-24T00:00:00Z',
          },
        ],
        web_search_available: false,
      })),
    });

    expect(fallback[unstable_serialize(['chats', 'recent', 20])]).toEqual({
      sessions: [
        {
          sessionId: 's-1',
          title: '',
          type: 'general_chat',
          updatedAt: '2026-02-24T00:00:00Z',
        },
      ],
      webSearchAvailable: false,
    });
  });
});
