import type { SWRFallback } from '@/lib/swrFallback';
import {
  prefetchGeneralChatRouteData,
  prefetchKbChatRouteData,
  prefetchKnowledgeBaseAddDocumentsRouteData,
  prefetchKnowledgeBaseDetailRouteData,
} from './serverFirstRoutePrefetch';

type SearchParamValue = string | string[] | undefined;
type SearchParamsRecord = { [key: string]: SearchParamValue };

export function resolveSingleSearchParamValue(value: SearchParamValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function createGeneralChatFallbackPromise(
  deps?: Parameters<typeof prefetchGeneralChatRouteData>[0]
): Promise<SWRFallback> {
  return prefetchGeneralChatRouteData(deps);
}

export function createKbChatFallbackPromise(
  deps?: Parameters<typeof prefetchKbChatRouteData>[0]
): Promise<SWRFallback> {
  return prefetchKbChatRouteData(deps);
}

interface KnowledgeBaseDetailFallbackPromiseDeps {
  prefetchFn?: typeof prefetchKnowledgeBaseDetailRouteData;
  prefetchDeps?: Parameters<typeof prefetchKnowledgeBaseDetailRouteData>[1];
}

export function createKnowledgeBaseDetailFallbackPromise(
  params: Promise<{ kbId: string }>,
  deps: KnowledgeBaseDetailFallbackPromiseDeps = {}
): Promise<SWRFallback> {
  const prefetchFn = deps.prefetchFn ?? prefetchKnowledgeBaseDetailRouteData;

  return params.then(({ kbId }) => prefetchFn(kbId, deps.prefetchDeps));
}

interface KnowledgeBaseAddDocumentsFallbackPromiseDeps {
  prefetchFn?: typeof prefetchKnowledgeBaseAddDocumentsRouteData;
  prefetchDeps?: Parameters<typeof prefetchKnowledgeBaseAddDocumentsRouteData>[2];
}

export function createKnowledgeBaseAddDocumentsFallbackPromise(
  params: Promise<{ kbId: string }>,
  searchParams: Promise<SearchParamsRecord>,
  deps: KnowledgeBaseAddDocumentsFallbackPromiseDeps = {}
): Promise<SWRFallback> {
  const prefetchFn = deps.prefetchFn ?? prefetchKnowledgeBaseAddDocumentsRouteData;

  return Promise.all([params, searchParams]).then(([{ kbId }, resolvedSearchParams]) => {
    const jobId = resolveSingleSearchParamValue(resolvedSearchParams.job);
    return prefetchFn(kbId, jobId, deps.prefetchDeps);
  });
}
