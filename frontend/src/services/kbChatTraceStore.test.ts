import { describe, expect, it } from 'vitest';

import { reduceKbChatTraceState } from './kbChatTraceStore';

const ctx = {
  totalNodes: 20,
  resolveNodeLabel: (nodeId: string) => nodeId,
};

describe('kbChatTraceStore', () => {
  it('keeps updates action idempotent for repeated event payload', () => {
    const base = {};
    const action = {
      type: 'updates' as const,
      raw: {
        run_id: 'run-1',
        chunk: {
          retrieve: { ok: true },
        },
      },
      ts: '2026-01-01T00:00:00.000Z',
    };
    const once = reduceKbChatTraceState(base, action, ctx);
    const twice = reduceKbChatTraceState(once, action, ctx);

    expect(twice.pipelineSteps?.length).toBe(1);
    expect(twice.nodeTimeline?.length).toBe(1);
  });

  it('deduplicates repeated node_io events', () => {
    const action = {
      type: 'node_io' as const,
      raw: {
        run_id: 'run-1',
        node_id: 'retrieve',
        node_name: 'retrieve',
        phase: 'end',
        ts: '2026-01-01T00:00:00.000Z',
      },
    };
    const once = reduceKbChatTraceState({}, action, ctx);
    const twice = reduceKbChatTraceState(once, action, ctx);
    expect(twice.nodeIoEvents?.length).toBe(1);
    expect(twice.nodeTimeline?.length).toBe(1);
  });

  it('keeps node_io display input/output items for detail rendering', () => {
    const next = reduceKbChatTraceState(
      {},
      {
        type: 'node_io',
        raw: {
          run_id: 'run-1',
          node_id: 'rewrite_branch_retrieve',
          node_name: 'rewrite_branch_retrieve',
          phase: 'end',
          display_input_items: [{ key: 'query', label: '输入查询', value: '火车票退改签' }],
          display_output_items: [{ key: 'retrieval_count', label: '证据数', value: '4' }],
          ts: '2026-01-01T00:00:00.000Z',
        },
      },
      ctx
    );
    expect(next.nodeIoEvents?.[0]?.display_input_items?.[0]?.key).toBe('query');
    expect(next.nodeIoEvents?.[0]?.display_output_items?.[0]?.key).toBe('retrieval_count');
  });

  it('rebuilds step order by timestamp', () => {
    let state = reduceKbChatTraceState(
      {},
      {
        type: 'updates',
        raw: { run_id: 'run-1', chunk: { b_node: { ok: true } } },
        ts: '2026-01-01T00:00:02.000Z',
      },
      ctx
    );
    state = reduceKbChatTraceState(
      state,
      {
        type: 'updates',
        raw: { run_id: 'run-1', chunk: { a_node: { ok: true } } },
        ts: '2026-01-01T00:00:01.000Z',
      },
      ctx
    );
    expect(state.pipelineSteps?.map((step) => step.step_id)).toEqual(['a_node', 'b_node']);
  });

  it('emits warning on node_io field drift', () => {
    const next = reduceKbChatTraceState(
      {},
      {
        type: 'node_io',
        raw: {
          event_type: 'node_io',
          node_name: 'retrieve',
        },
      },
      ctx
    );
    expect(next.traceWarnings?.[0]).toContain('field drift');
  });
});
