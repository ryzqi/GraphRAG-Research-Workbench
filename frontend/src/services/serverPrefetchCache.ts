import { cache } from 'react';
import { getRecentChats } from './chats';
import { getBootstrapSubmission } from './bootstrapSubmissions';
import { getLatestIngestionBatch } from './ingestionBatches';
import {
  getKnowledgeBase,
  getKnowledgeBaseIngestionState,
  listSelectableKnowledgeBases,
} from './knowledgeBases';

const SERVER_PREFETCH_CACHE_REVALIDATE_SECONDS = 30;

// 研究/知识库详情类元数据允许短 TTL 复用，动态状态仍保持 no-store；
// 两类请求都关闭随机 request id header，避免服务端缓存键被每次请求打散。
const CACHEABLE_SERVER_GET_OPTIONS = {
  includeRequestIdHeader: false,
  next: { revalidate: SERVER_PREFETCH_CACHE_REVALIDATE_SECONDS },
} as const;

const DYNAMIC_SERVER_GET_OPTIONS = {
  includeRequestIdHeader: false,
  cache: 'no-store',
} as const;

export const getServerPrefetchRecentChats = cache(async (limit: number) =>
  getRecentChats(limit, DYNAMIC_SERVER_GET_OPTIONS)
);

export const getServerPrefetchSelectableKnowledgeBases = cache(async () =>
  listSelectableKnowledgeBases(undefined, CACHEABLE_SERVER_GET_OPTIONS)
);

export const getServerPrefetchKnowledgeBase = cache(async (kbId: string) =>
  getKnowledgeBase(kbId, CACHEABLE_SERVER_GET_OPTIONS)
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
