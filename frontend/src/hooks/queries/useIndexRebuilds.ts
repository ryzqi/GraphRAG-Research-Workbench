/**
 * Index rebuild hooks based on SWR
 */
import { getIndexRebuildJob, type IndexRebuildJob } from '../../services/indexRebuilds';
import { useApiQuery } from '../../lib/swr';

const NO_ID = '__none__';

export const indexRebuildKeys = {
  all: ['indexRebuilds'] as const,
  job: (id: string | undefined) => [...indexRebuildKeys.all, 'job', id ?? NO_ID] as const,
};

export function useIndexRebuildJob(jobId: string | undefined) {
  return useApiQuery<IndexRebuildJob>(
    jobId ? indexRebuildKeys.job(jobId) : null,
    jobId ? () => getIndexRebuildJob(jobId) : null,
    {
      refreshInterval: (latestJob) => {
        const status = (latestJob as IndexRebuildJob | undefined)?.status;
        return status === 'queued' || status === 'running' ? 2_000 : 0;
      },
    }
  );
}
