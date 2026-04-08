import { describe, expect, it } from 'vitest';

import { buildQueueHealthHint } from './queueHealthDiagnostics';

describe('buildQueueHealthHint', () => {
  it('reports research queue issues for queued research sessions', () => {
    const message = buildQueueHealthHint({
      snapshot: {
        workers_online: true,
        queues: {
          default: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
          dispatch: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
          ingestion: { consumer_count: 1, ready_messages: 0, required: true, healthy: true },
          research: { consumer_count: 0, ready_messages: 2, required: true, healthy: false },
        },
        stuck_summary: {
          bootstrap_queued_jobs: 0,
          processing_docs_over_sla: 0,
          research_queued_sessions: 1,
        },
        timestamp: '2026-04-08T09:35:00.000Z',
      } as any,
      waitingBootstrapBatch: false,
      batchProcessing: false,
      waitingResearchSession: true,
    } as any);

    expect(message).toContain('research');
  });
});
