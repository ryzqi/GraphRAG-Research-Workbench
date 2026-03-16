import { describe, expect, it } from 'vitest';

import { KB_CHAT_CUSTOM_EVENT_TYPES } from './chats';
import { reduceKbChatTraceState } from './kbChatTraceStore';

const ctx = {
  totalNodes: 20,
  resolveNodeLabel: (nodeId: string) => nodeId,
};

describe('kbChatTraceStore', () => {
  it('keeps an explicit kb chat custom event taxonomy', () => {
    expect(KB_CHAT_CUSTOM_EVENT_TYPES).toEqual([
      'node_io',
      'answer_review_subcheck',
      'answer_review_fused',
      'guardrail_warning',
      'heartbeat',
    ]);
  });

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
          node_id: 'retrieve_subquery',
          node_name: 'retrieve_subquery',
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

  it('preserves node_path from node_io payload for trace details', () => {
    const next = reduceKbChatTraceState(
      {},
      {
        type: 'node_io',
        raw: {
          run_id: 'run-1',
          node_id: 'retrieve_subquery',
          node_name: 'retrieve_subquery',
          node_path: ['retrieval_subgraph', 'dispatch_subqueries', 'retrieve_subquery'],
          phase: 'end',
          ts: '2026-01-01T00:00:00.000Z',
        },
      },
      ctx
    );

    expect(next.nodeIoEvents?.[0]).toMatchObject({
      node_path: ['retrieval_subgraph', 'dispatch_subqueries', 'retrieve_subquery'],
    });
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

  it('applies state events to run state, pipeline steps, and timeline', () => {
    let state = reduceKbChatTraceState(
      {},
      {
        type: 'updates',
        raw: { run_id: 'run-1', chunk: { preprocess_subgraph: { ok: true } } },
        ts: '2026-01-01T00:00:00.000Z',
      },
      ctx
    );
    state = reduceKbChatTraceState(
      state,
      {
        type: 'node_io',
        raw: {
          run_id: 'run-1',
          node_id: 'merge_context',
          node_name: 'merge_context',
          phase: 'start',
          ts: '2026-01-01T00:00:01.000Z',
        },
      },
      ctx
    );

    const next = reduceKbChatTraceState(
      state,
      {
        type: 'state',
        raw: {
          run_id: 'run-1',
          run_status: 'waiting_user',
          current_step_id: 'merge_context',
          current_step_label: '上下文合并',
          current_step_status: 'waiting_user',
          current_node: 'merge_context',
          attempt: 2,
          message: '需要补充信息',
          state_version: 3,
          active_path: ['merge_context'],
          progress: { completed: 1, total: 20, percent: 5 },
          ts: '2026-01-01T00:00:02.000Z',
        },
      },
      ctx
    );

    expect(next.runState?.active_path).toEqual(['preprocess_subgraph', 'merge_context']);
    expect(next.runState?.current_step_status).toBe('waiting_user');
    expect(next.pipelineSteps?.find((step) => step.step_id === 'merge_context')).toMatchObject({
      label: '上下文合并',
      status: 'waiting_user',
      node: 'merge_context',
      message: '需要补充信息',
    });
    expect(next.nodeTimeline?.at(-1)).toMatchObject({
      source: 'state',
      step_id: 'merge_context',
      status: 'waiting_user',
      run_status: 'waiting_user',
      message: '需要补充信息',
    });
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

  it('salvages custom review signals into timeline entries instead of dropping them silently', () => {
    const next = reduceKbChatTraceState(
      {},
      {
        type: 'custom',
        raw: {
          run_id: 'run-1',
          event_type: 'answer_review_fused',
          node_name: 'answer_review_fuse',
          passed: false,
          reason: 'citation_mismatch',
          goto: 'answer_repair',
          ts: '2026-01-01T00:00:00.000Z',
        },
      },
      ctx
    );

    expect(next.nodeTimeline?.at(-1)).toMatchObject({
      source: 'ui',
      step_id: 'answer_review_fuse',
      event_type: 'review_signal',
      message: 'citation_mismatch',
    });
    expect(next.traceWarnings ?? []).toHaveLength(0);
  });

  it('keeps heartbeat custom events benign while warning on unhandled custom taxonomy', () => {
    const heartbeat = reduceKbChatTraceState(
      {},
      {
        type: 'custom',
        raw: {
          run_id: 'run-1',
          event_type: 'heartbeat',
          ts: '2026-01-01T00:00:00.000Z',
        },
      },
      ctx
    );
    expect(heartbeat.traceWarnings ?? []).toHaveLength(0);

    const unhandled = reduceKbChatTraceState(
      heartbeat,
      {
        type: 'custom',
        raw: {
          run_id: 'run-1',
          event_type: 'mystery_taxonomy',
          ts: '2026-01-01T00:00:01.000Z',
        },
      },
      ctx
    );
    expect(unhandled.traceWarnings?.at(-1)).toContain('unhandled custom event');
  });
});
