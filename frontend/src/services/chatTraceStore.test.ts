import { describe, expect, it } from 'vitest';

import { createTraceStore } from './chatTraceStore';

describe('createTraceStore', () => {
  it('applies step and state events', () => {
    const store = createTraceStore();

    store.apply({
      event: 'step',
      version: '1.0',
      payload: {
        step_id: 'retrieve',
        label: 'Retrieve',
        status: 'started',
        ts: '2026-01-01T00:00:00.000Z',
      },
    });

    store.apply({
      event: 'state',
      version: '1.0',
      payload: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'retrieve',
        current_step_label: 'Retrieve',
        current_step_status: 'started',
        current_node: 'retrieve',
        attempt: 1,
        message: null,
        progress: { completed: 0, total: 1, percent: 0 },
        ts: '2026-01-01T00:00:01.000Z',
      },
    });

    const snapshot = store.snapshot();
    expect(snapshot.pipelineSteps?.length).toBe(1);
    expect(snapshot.runId).toBe('run-1');
    expect(snapshot.runState?.run_status).toBe('running');
    expect(snapshot.nodeTimeline?.length).toBeGreaterThanOrEqual(2);
  });

  it('records node/tool trace events into timeline', () => {
    const store = createTraceStore();

    store.apply({
      event: 'node_trace',
      version: '2.0',
      payload: {
        run_id: 'run-2',
        node_id: 'retrieve#1',
        node_name: 'retrieve',
        phase: 'completed',
        latency_ms: 42,
        ts: '2026-01-01T00:00:02.000Z',
      },
    });

    store.apply({
      event: 'tool_trace',
      version: '2.0',
      payload: {
        run_id: 'run-2',
        node_id: 'retrieve#1',
        node_name: 'retrieve',
        tool_name: 'kb_retrieve',
        call_index: 1,
        input_summary: 'what is rag',
        output_summary: 'rag is retrieval augmented generation',
        ts: '2026-01-01T00:00:03.000Z',
      },
    });

    const snapshot = store.snapshot();
    expect(snapshot.nodeTimeline?.some((item) => item.event_type === 'node_trace')).toBe(true);
    expect(snapshot.nodeTimeline?.some((item) => item.event_type === 'tool_trace')).toBe(true);
  });
});
