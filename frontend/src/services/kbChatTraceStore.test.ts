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

  it('tracks parallel execution instances for the same node separately', () => {
    let state = reduceKbChatTraceState(
      {},
      {
        type: 'step',
        raw: {
          run_id: 'run-1',
          execution_id: 'task-1',
          step_id: 'retrieve_subquery',
          label: '子查询检索 #1',
          status: 'started',
          node: 'retrieve_subquery',
          ts: '2026-01-01T00:00:01.000Z',
        },
      },
      ctx
    );

    state = reduceKbChatTraceState(
      state,
      {
        type: 'step',
        raw: {
          run_id: 'run-1',
          execution_id: 'task-2',
          step_id: 'retrieve_subquery',
          label: '子查询检索 #2',
          status: 'started',
          node: 'retrieve_subquery',
          ts: '2026-01-01T00:00:02.000Z',
        },
      },
      ctx
    );

    expect(state.executionOrder).toEqual(['task-1', 'task-2']);
    expect(state.executionsById?.['task-1']).toMatchObject({
      execution_id: 'task-1',
      node_name: 'retrieve_subquery',
      node_label: 'retrieve_subquery',
      status: 'started',
      started_at: '2026-01-01T00:00:01.000Z',
    });
    expect(state.executionsById?.['task-2']).toMatchObject({
      execution_id: 'task-2',
      node_name: 'retrieve_subquery',
      node_label: 'retrieve_subquery',
      status: 'started',
      started_at: '2026-01-01T00:00:02.000Z',
    });
  });

  it('binds node_io detail payloads onto the matching execution instance', () => {
    let state = reduceKbChatTraceState(
      {},
      {
        type: 'step',
        raw: {
          run_id: 'run-1',
          execution_id: 'task-1',
          step_id: 'retrieve_subquery',
          label: '子查询检索',
          status: 'started',
          node: 'retrieve_subquery',
          ts: '2026-01-01T00:00:01.000Z',
        },
      },
      ctx
    );

    state = reduceKbChatTraceState(
      state,
      {
        type: 'node_io',
        raw: {
          run_id: 'run-1',
          execution_id: 'task-1',
          node_id: 'retrieve_subquery',
          node_name: 'retrieve_subquery',
          node_path: ['retrieval_subgraph:task-1', 'retrieve_subquery'],
          phase: 'end',
          display_input_items: [{ key: 'query', label: '输入查询', value: 'CoT 和 ToT 区别' }],
          display_output_items: [{ key: 'retrieval_count', label: '证据数', value: '4' }],
          latency_ms: 88,
          ts: '2026-01-01T00:00:02.000Z',
        },
      },
      ctx
    );

    expect(state.executionsById?.['task-1']).toMatchObject({
      execution_id: 'task-1',
      status: 'completed',
      ended_at: '2026-01-01T00:00:02.000Z',
      node_path: ['retrieval_subgraph:task-1', 'retrieve_subquery'],
      input_items: [{ key: 'query', label: '输入查询', value: 'CoT 和 ToT 区别' }],
      output_items: [{ key: 'retrieval_count', label: '证据数', value: '4' }],
      latency_ms: 88,
    });
  });

  it('keeps state events as authoritative run snapshots after state_version appears', () => {
    const fromState = reduceKbChatTraceState(
      {},
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
          active_path: ['preprocess_subgraph', 'merge_context'],
          progress: { completed: 2, total: 20, percent: 10 },
          ts: '2026-01-01T00:00:02.000Z',
        },
      },
      ctx
    );

    const next = reduceKbChatTraceState(
      fromState,
      {
        type: 'step',
        raw: {
          run_id: 'run-1',
          execution_id: 'task-2',
          step_id: 'retrieve_subquery',
          label: '子查询检索',
          status: 'started',
          node: 'retrieve_subquery',
          ts: '2026-01-01T00:00:03.000Z',
        },
      },
      ctx
    );

    expect(next.runState).toMatchObject({
      current_step_id: 'merge_context',
      current_step_status: 'waiting_user',
      current_node: 'merge_context',
      active_path: ['preprocess_subgraph', 'merge_context'],
    });
    expect(next.executionsById?.['task-2']).toMatchObject({
      execution_id: 'task-2',
      status: 'started',
    });
  });

  it('ignores updates as a right-panel truth source', () => {
    const next = reduceKbChatTraceState(
      {},
      {
        type: 'updates',
        raw: {
          run_id: 'run-1',
          chunk: {
            retrieve_subquery: { ok: true },
          },
        },
      },
      ctx
    );

    expect(next.executionOrder).toEqual([]);
    expect(next.executionsById).toEqual({});
  });

  it('warns when node_io arrives without execution identity', () => {
    const next = reduceKbChatTraceState(
      {},
      {
        type: 'node_io',
        raw: {
          run_id: 'run-1',
          node_id: 'retrieve_subquery',
          node_name: 'retrieve_subquery',
          phase: 'end',
          ts: '2026-01-01T00:00:02.000Z',
        },
      },
      ctx
    );

    expect(next.executionOrder).toEqual([]);
    expect(next.traceWarnings?.at(-1)).toContain('execution_id');
  });

  it('keeps heartbeat benign while warning on unhandled custom taxonomy', () => {
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
