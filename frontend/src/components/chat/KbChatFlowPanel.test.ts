import { describe, expect, it } from 'vitest';

import {
  buildFallbackOutputItems,
  buildNodePathDetailItem,
  extractTraceCommandGoto,
} from './KbChatFlowPanel';

describe('KbChatFlowPanel', () => {
  it('prefers __trace_command__ over legacy __command__ for branch targets', () => {
    expect(
      extractTraceCommandGoto({
        __trace_command__: { goto: 'draft_generate' },
        __command__: { goto: 'generate' },
      })
    ).toBe('draft_generate');

    expect(
      extractTraceCommandGoto({
        __command__: { goto: 'generate' },
      })
    ).toBe('generate');

    expect(extractTraceCommandGoto({})).toBeNull();
  });

  it('formats node_path into a trace-friendly detail item', () => {
    expect(
      buildNodePathDetailItem({
        run_id: 'run-1',
        node_id: 'retrieve_subquery',
        node_name: 'retrieve_subquery',
        node_path: ['retrieval_subgraph', 'dispatch_subqueries', 'retrieve_subquery'],
        phase: 'end',
        ts: '2026-01-01T00:00:00.000Z',
      })
    ).toEqual({
      key: 'node_path',
      label: '执行路径',
      value: ['检索子图', '子查询派发', '子查询检索'],
    });
  });

  it('uses canonical routing record for answer_subgraph fallback output items', () => {
    const items = buildFallbackOutputItems('answer_subgraph', {
      output_snapshot: {
        routing_decisions: {
          answer_subgraph: {
            next_node: 'confidence_calibrate',
            action: 'none',
            reason: 'passed',
          },
        },
        stage_summaries: {
          answer_subgraph: {
            next_step: 'force_exit',
            reason: 'stale_stage_reason',
          },
        },
        reflection: {
          reason: 'stale_reflection_reason',
        },
        best_answer: '答案 [S1]',
      },
    } as never);

    const byKey = new Map(items.map((item) => [item.key, item.value]));
    expect(byKey.get('next_node')).toBe('confidence_calibrate');
    expect(byKey.get('reason')).toBe('passed');
  });

  it('does not synthesize answer_subgraph routing details from legacy summary fields', () => {
    const items = buildFallbackOutputItems('answer_subgraph', {
      output_snapshot: {
        stage_summaries: {
          answer_subgraph: {
            next_step: 'force_exit',
            reason: 'stale_stage_reason',
          },
        },
        reflection: {
          reason: 'stale_reflection_reason',
        },
      },
    } as never);

    const keys = items.map((item) => item.key);
    expect(keys).not.toContain('next_node');
    expect(keys).not.toContain('reason');
  });
});
