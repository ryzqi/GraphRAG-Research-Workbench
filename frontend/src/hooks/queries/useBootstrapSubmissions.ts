import { useApiMutation, useApiQuery } from '../../lib/swr';
import {
  createBootstrapKnowledgeBase,
  createBootstrapSubmission,
  finalizeBootstrapSubmission,
  getBootstrapSubmission,
  type BootstrapSubmission,
  type BootstrapCreateKnowledgeBaseRequest,
  type BootstrapCreateKnowledgeBaseResponse,
  type BootstrapSubmissionCreateRequest,
  type BootstrapSubmissionFinalizeResponse,
  type BootstrapSubmissionStatus,
} from '../../services/bootstrapSubmissions';
import { DEFAULT_STATUS_POLLING_INTERVAL_MS } from '../../constants/runtimeDefaults';

const NO_ID = '__none__';

interface UseCreateBootstrapSubmissionOptions {
  invalidateMode?: 'blocking' | 'background';
}

const KEYS = {
  all: ['bootstrapSubmissions'] as const,
  detail: (id: string | undefined) => [...KEYS.all, 'detail', id ?? NO_ID] as const,
};

export function isBootstrapSubmissionTerminal(status: BootstrapSubmissionStatus): boolean {
  return status === 'completed' || status === 'failed';
}

export function shouldPollBootstrapSubmission(
  job: Pick<BootstrapSubmission, 'status'> | undefined
): boolean {
  if (!job) {
    return false;
  }
  return !isBootstrapSubmissionTerminal(job.status);
}

export function useBootstrapSubmission(jobId: string | undefined) {
  return useApiQuery(
    jobId ? KEYS.detail(jobId) : null,
    jobId ? () => getBootstrapSubmission(jobId) : null,
    {
      skipInitialFetchIfCached: true,
      refreshInterval: (latest) =>
        shouldPollBootstrapSubmission(latest as BootstrapSubmission | undefined)
          ? DEFAULT_STATUS_POLLING_INTERVAL_MS
          : 0,
    }
  );
}

export function useCreateBootstrapSubmission(options?: UseCreateBootstrapSubmissionOptions) {
  const invalidateMode = options?.invalidateMode ?? 'background';

  return useApiMutation(
    (data: BootstrapSubmissionCreateRequest) => createBootstrapSubmission(data),
    {
      onSuccess: async (resp, __, { invalidate }) => {
        const keysToInvalidate: Array<readonly unknown[]> = [
          KEYS.all,
          ['knowledgeBases'],
          ['ingestionBatches'],
        ];
        if (resp.job_id) {
          keysToInvalidate.push(KEYS.detail(resp.job_id));
        }

        const invalidatePromise = invalidate(keysToInvalidate);
        if (invalidateMode === 'blocking') {
          await invalidatePromise;
          return;
        }
        void invalidatePromise;
      },
    }
  );
}

export function useCreateBootstrapKnowledgeBase(options?: UseCreateBootstrapSubmissionOptions) {
  const invalidateMode = options?.invalidateMode ?? 'background';

  return useApiMutation(
    (data: BootstrapCreateKnowledgeBaseRequest) => createBootstrapKnowledgeBase(data),
    {
      onSuccess: async (resp: BootstrapCreateKnowledgeBaseResponse, __, { invalidate }) => {
        const keysToInvalidate: Array<readonly unknown[]> = [
          KEYS.all,
          ['knowledgeBases'],
          ['ingestionBatches'],
        ];
        if (resp.job_id) {
          keysToInvalidate.push(KEYS.detail(resp.job_id));
        }

        const invalidatePromise = invalidate(keysToInvalidate);
        if (invalidateMode === 'blocking') {
          await invalidatePromise;
          return;
        }
        void invalidatePromise;
      },
    }
  );
}

export function useFinalizeBootstrapSubmission() {
  return useApiMutation((jobId: string) => finalizeBootstrapSubmission(jobId), {
    onSuccess: async (resp: BootstrapSubmissionFinalizeResponse, _, { invalidate }) => {
      const keysToInvalidate: Array<readonly unknown[]> = [KEYS.all, ['ingestionBatches']];
      if (resp.job_id) {
        keysToInvalidate.push(KEYS.detail(resp.job_id));
      }
      await invalidate(keysToInvalidate);
    },
  });
}

export { KEYS as bootstrapSubmissionKeys };
export type { BootstrapSubmissionStatus };
