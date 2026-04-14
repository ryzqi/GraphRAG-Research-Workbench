import { describe, expect, it } from 'vitest';

import { docPresentationStatus } from '../../components/ingestion/statusPresentation';
import { resolveRecoverableBatchId } from '../../services/ingestionBatchRecovery';
import { isBatchActive, isBatchTerminal } from './useIngestionBatches';
import { shouldPollBootstrapSubmission } from './useBootstrapSubmissions';

describe('polling rules', () => {
  it('stops bootstrap polling once a live batch is available', () => {
    expect(
      shouldPollBootstrapSubmission({
        status: 'running',
        batch_id: 'batch-1',
      } as never)
    ).toBe(false);
  });

  it('keeps bootstrap polling while upload coordination is still pending', () => {
    expect(
      shouldPollBootstrapSubmission({
        status: 'queued_upload',
        batch_id: null,
      } as never)
    ).toBe(true);
  });

  it('treats failed and canceled batches as terminal', () => {
    expect(isBatchTerminal({ status: 'failed' } as never)).toBe(true);
    expect(isBatchTerminal({ status: 'canceled' } as never)).toBe(true);
  });

  it('treats queued batches as active', () => {
    expect(isBatchActive({ status: 'queued' } as never)).toBe(true);
    expect(isBatchActive({ status: 'processing' } as never)).toBe(true);
  });

  it('recovers queued or running batches after submit-side timeout', () => {
    expect(resolveRecoverableBatchId({ id: 'batch-1', status: 'queued' } as never)).toBe(
      'batch-1'
    );
    expect(
      resolveRecoverableBatchId({ id: 'batch-2', status: 'processing' } as never)
    ).toBe('batch-2');
  });

  it('maps explicit doc statuses without relying on error-code inference', () => {
    expect(docPresentationStatus({ status: 'queued', error_code: null } as never)).toBe(
      'processing'
    );
    expect(
      docPresentationStatus({ status: 'succeeded', error_code: null } as never)
    ).toBe('succeeded');
    expect(
      docPresentationStatus({ status: 'failed', error_code: 'DOC_QUEUE_TIMEOUT' } as never)
    ).toBe('failed');
    expect(
      docPresentationStatus({ status: 'canceled', error_code: 'DOC_CANCELED' } as never)
    ).toBe('canceled');
  });
});
