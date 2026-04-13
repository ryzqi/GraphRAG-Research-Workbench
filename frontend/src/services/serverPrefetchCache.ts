import { cache } from 'react';
import { getServerPrefetchCacheRevalidateSeconds } from '../constants/runtimeDefaults';
import { getRecentChats } from './chats';
import { getBootstrapSubmission } from './bootstrapSubmissions';
import { getLatestIngestionBatch } from './ingestionBatches';
import {
  getKnowledgeBase,
  getKnowledgeBaseIngestionState,
  listSelectableKnowledgeBases,
} from './knowledgeBases';
import { getPublicRuntimeConfig } from './runtimeConfig';

const getCacheableServerGetOptions = cache(async () => {
  const runtimeConfig = await getPublicRuntimeConfig({
    includeRequestIdHeader: false,
    cache: 'no-store',
  });
  return {
    includeRequestIdHeader: false,
    next: {
      revalidate: getServerPrefetchCacheRevalidateSeconds(runtimeConfig),
    },
  } as const;
});

const DYNAMIC_SERVER_GET_OPTIONS = {
  includeRequestIdHeader: false,
  cache: 'no-store',
} as const;

export const getServerPrefetchRecentChats = cache(async (limit: number) =>
  getRecentChats(limit, DYNAMIC_SERVER_GET_OPTIONS)
);

export const getServerPrefetchSelectableKnowledgeBases = cache(async () =>
  listSelectableKnowledgeBases(undefined, await getCacheableServerGetOptions())
);

export const getServerPrefetchKnowledgeBase = cache(async (kbId: string) =>
  getKnowledgeBase(kbId, await getCacheableServerGetOptions())
);

export const getServerPrefetchKnowledgeBaseIngestionState = cache(async (kbId: string) =>
  getKnowledgeBaseIngestionState(kbId, DYNAMIC_SERVER_GET_OPTIONS)
);

export const getServerPrefetchLatestIngestionBatch = cache(async (kbId: string) =>
  getLatestIngestionBatch(kbId, DYNAMIC_SERVER_GET_OPTIONS)
);

export const getServerPrefetchBootstrapSubmission = cache(async (jobId: string) =>
  getBootstrapSubmission(jobId, DYNAMIC_SERVER_GET_OPTIONS)
);
