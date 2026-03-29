import { appendSWRFallback, type SWRFallback } from '../lib/swrFallback';
import {
  getRecentChats,
  type RecentChatListResponse,
  type WebSearchStatus,
} from './chats';
import { getBootstrapSubmission, type BootstrapSubmission } from './bootstrapSubmissions';
import { getLatestIngestionBatch, type IngestionBatch } from './ingestionBatches';
import {
  getKnowledgeBase,
  getKnowledgeBaseIngestionState,
  listSelectableKnowledgeBases,
  type KnowledgeBase,
  type KnowledgeBaseIngestionState,
} from './knowledgeBases';

function toRecentHistoryData(input: RecentChatListResponse) {
  return {
    sessions: input.items.map((item) => ({
      sessionId: item.id,
      title: item.title ?? '',
      type: item.session_type,
      updatedAt: item.updated_at,
    })),
    webSearch: input.web_search ?? ({
      configured: false,
      verified: false,
      mode: 'down',
      providers: [],
    } satisfies WebSearchStatus),
  };
}

interface GeneralChatPrefetchDeps {
  getRecentChatsFn?: (limit?: number) => Promise<RecentChatListResponse>;
}

export async function prefetchGeneralChatRouteData(
  deps: GeneralChatPrefetchDeps = {}
): Promise<SWRFallback> {
  const fallback: SWRFallback = {};
  const recent = await (deps.getRecentChatsFn ?? getRecentChats)(20).catch(() => null);
  if (recent) {
    appendSWRFallback(fallback, ['chats', 'recent', 20], toRecentHistoryData(recent));
  }
  return fallback;
}

interface KbChatPrefetchDeps {
  getRecentChatsFn?: (limit?: number) => Promise<RecentChatListResponse>;
  listSelectableKnowledgeBasesFn?: () => Promise<{ items: KnowledgeBase[] }>;
}

export async function prefetchKbChatRouteData(
  deps: KbChatPrefetchDeps = {}
): Promise<SWRFallback> {
  const fallback: SWRFallback = {};
  const [recent, selectable] = await Promise.all([
    (deps.getRecentChatsFn ?? getRecentChats)(20).catch(() => null),
    (deps.listSelectableKnowledgeBasesFn ?? listSelectableKnowledgeBases)().catch(() => null),
  ]);

  if (recent) {
    appendSWRFallback(fallback, ['chats', 'recent', 20], toRecentHistoryData(recent));
  }
  if (selectable) {
    appendSWRFallback(fallback, ['knowledgeBases', 'selectable'], selectable.items);
  }
  return fallback;
}

interface KnowledgeBaseDetailPrefetchDeps {
  getKnowledgeBaseFn?: (kbId: string) => Promise<KnowledgeBase>;
  getKnowledgeBaseIngestionStateFn?: (kbId: string) => Promise<KnowledgeBaseIngestionState>;
  getLatestIngestionBatchFn?: (kbId: string) => Promise<IngestionBatch>;
}

export async function prefetchKnowledgeBaseDetailRouteData(
  kbId: string,
  deps: KnowledgeBaseDetailPrefetchDeps = {}
): Promise<SWRFallback> {
  const fallback: SWRFallback = {};
  const [kb, ingestionState, latestBatch] = await Promise.all([
    (deps.getKnowledgeBaseFn ?? getKnowledgeBase)(kbId).catch(() => null),
    (deps.getKnowledgeBaseIngestionStateFn ?? getKnowledgeBaseIngestionState)(kbId).catch(
      () => null
    ),
    (deps.getLatestIngestionBatchFn ?? getLatestIngestionBatch)(kbId).catch(() => null),
  ]);

  if (kb) {
    appendSWRFallback(fallback, ['knowledgeBases', 'detail', kbId], kb);
  }
  if (ingestionState) {
    appendSWRFallback(fallback, ['knowledgeBases', 'ingestionState', kbId], ingestionState);
  }
  if (latestBatch) {
    appendSWRFallback(fallback, ['ingestionBatches', 'latest', kbId], latestBatch);
  }
  return fallback;
}

interface KnowledgeBaseAddDocumentsPrefetchDeps {
  getKnowledgeBaseFn?: (kbId: string) => Promise<KnowledgeBase>;
  getLatestIngestionBatchFn?: (kbId: string) => Promise<IngestionBatch>;
  getBootstrapSubmissionFn?: (jobId: string) => Promise<BootstrapSubmission>;
}

export async function prefetchKnowledgeBaseAddDocumentsRouteData(
  kbId: string,
  jobId: string | undefined,
  deps: KnowledgeBaseAddDocumentsPrefetchDeps = {}
): Promise<SWRFallback> {
  const fallback: SWRFallback = {};
  const [kb, latestBatch, bootstrapJob] = await Promise.all([
    (deps.getKnowledgeBaseFn ?? getKnowledgeBase)(kbId).catch(() => null),
    (deps.getLatestIngestionBatchFn ?? getLatestIngestionBatch)(kbId).catch(() => null),
    jobId
      ? (deps.getBootstrapSubmissionFn ?? getBootstrapSubmission)(jobId).catch(() => null)
      : Promise.resolve(null),
  ]);

  if (kb) {
    appendSWRFallback(fallback, ['knowledgeBases', 'detail', kbId], kb);
  }
  if (latestBatch) {
    appendSWRFallback(fallback, ['ingestionBatches', 'latest', kbId], latestBatch);
  }
  if (jobId && bootstrapJob) {
    appendSWRFallback(fallback, ['bootstrapSubmissions', 'detail', jobId], bootstrapJob);
  }
  return fallback;
}
