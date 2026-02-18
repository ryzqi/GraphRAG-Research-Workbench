import type { IngestionBatch } from './ingestionBatches';
import { HttpError } from './http';

const RECOVERABLE_STATUSES = new Set([0, 408, 499]);

export function shouldRecoverAfterSubmitError(error: unknown): boolean {
  if (!(error instanceof HttpError)) {
    return false;
  }
  return RECOVERABLE_STATUSES.has(error.status);
}

export function resolveRecoverableBatchId(batch: IngestionBatch | null): string | null {
  if (!batch) {
    return null;
  }
  return batch.status === 'processing' ? batch.id : null;
}
