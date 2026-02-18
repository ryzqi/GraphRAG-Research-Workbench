import { describe, expect, it } from 'vitest';

import type { IngestionBatch } from './ingestionBatches';
import { resolveRecoverableBatchId, shouldRecoverAfterSubmitError } from './ingestionBatchRecovery';
import { HttpError } from './http';

function createBatch(overrides: Partial<IngestionBatch> = {}): IngestionBatch {
  return {
    id: 'batch-1',
    kb_id: 'kb-1',
    config_snapshot_id: 'snapshot-1',
    config_version: 1,
    is_bootstrap: false,
    status: 'processing',
    total_docs: 1,
    succeeded_docs: 0,
    failed_docs: 0,
    canceled_docs: 0,
    succeeded_chunks: 0,
    error_summary: null,
    created_at: '2026-02-18T18:00:00.000Z',
    started_at: '2026-02-18T18:00:00.000Z',
    finished_at: null,
    docs: [],
    ...overrides,
  };
}

describe('shouldRecoverAfterSubmitError', () => {
  it('returns true for timeout/network/cancel errors', () => {
    expect(shouldRecoverAfterSubmitError(new HttpError('timeout', 408))).toBe(true);
    expect(shouldRecoverAfterSubmitError(new HttpError('cancel', 499))).toBe(true);
    expect(shouldRecoverAfterSubmitError(new HttpError('network', 0))).toBe(true);
  });

  it('returns false for normal business errors', () => {
    expect(shouldRecoverAfterSubmitError(new HttpError('bad request', 400))).toBe(false);
    expect(shouldRecoverAfterSubmitError(new HttpError('conflict', 409))).toBe(false);
    expect(shouldRecoverAfterSubmitError(new Error('unknown'))).toBe(false);
  });
});

describe('resolveRecoverableBatchId', () => {
  it('returns batch id only when latest batch is processing', () => {
    expect(resolveRecoverableBatchId(createBatch({ status: 'processing' }))).toBe('batch-1');
    expect(resolveRecoverableBatchId(createBatch({ status: 'completed' }))).toBeNull();
    expect(resolveRecoverableBatchId(null)).toBeNull();
  });
});
