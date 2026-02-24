import { useParams, useSearchParams } from 'next/navigation';
import {
  useCancelIngestionBatch,
  useCreateIngestionBatch,
  useRetryIngestionBatch,
} from './queries/useIngestionBatches';
import {
  useBootstrapSubmission,
  useFinalizeBootstrapSubmission,
} from './queries/useBootstrapSubmissions';
import { useKnowledgeBase } from './queries/useKnowledgeBases';

export function useKnowledgeBaseAddDocumentsData() {
  const params = useParams<{ kbId: string }>();
  const searchParams = useSearchParams();
  const kbId = Array.isArray(params.kbId) ? params.kbId[0] : params.kbId;
  const initialBatchId = searchParams.get('batch') ?? undefined;
  const jobId = searchParams.get('job') ?? undefined;

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const createBatchMutation = useCreateIngestionBatch({
    invalidateMode: 'background',
  });
  const finalizeBootstrapMutation = useFinalizeBootstrapSubmission();
  const retryBatchMutation = useRetryIngestionBatch();
  const cancelBatchMutation = useCancelIngestionBatch();
  const bootstrapJobQuery = useBootstrapSubmission(jobId);

  return {
    kbId,
    initialBatchId,
    jobId,
    kbQuery,
    createBatchMutation,
    finalizeBootstrapMutation,
    retryBatchMutation,
    cancelBatchMutation,
    bootstrapJobQuery,
  };
}
