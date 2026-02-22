import { describe, expect, it } from 'vitest';

import {
  buildQueueHealthHint,
  type QueueHealthSnapshot,
} from './queueHealthDiagnostics';

function buildSnapshot(
  overrides: Partial<QueueHealthSnapshot> = {}
): QueueHealthSnapshot {
  return {
    workers_online: true,
    queues: {
      default: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
      dispatch: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
      ingestion: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
    },
    stuck_summary: {
      bootstrap_queued_jobs: 0,
      processing_docs_over_sla: 0,
    },
    timestamp: '2026-02-22T12:00:00Z',
    ...overrides,
  };
}

describe('buildQueueHealthHint', () => {
  it('returns default-worker hint when bootstrap waits and default queue is unhealthy', () => {
    const snapshot = buildSnapshot({
      queues: {
        default: { consumer_count: 0, ready_messages: 2, required: true, healthy: false },
        dispatch: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
        ingestion: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
      },
    });

    expect(buildQueueHealthHint({ snapshot, waitingBootstrapBatch: true, batchProcessing: false })).toContain(
      'default'
    );
  });

  it('returns ingestion-worker hint when batch is processing and ingestion queue is unhealthy', () => {
    const snapshot = buildSnapshot({
      queues: {
        default: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
        dispatch: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
        ingestion: { consumer_count: 0, ready_messages: 5, required: true, healthy: false },
      },
    });

    expect(buildQueueHealthHint({ snapshot, waitingBootstrapBatch: false, batchProcessing: true })).toContain(
      'ingestion'
    );
  });
});

