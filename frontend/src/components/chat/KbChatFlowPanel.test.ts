import { describe, expect, it } from 'vitest';

import { buildNodePathDetailItem, extractTraceCommandGoto } from './KbChatFlowPanel';

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
      value: [
        '检索子图（retrieval_subgraph）',
        '子查询派发（dispatch_subqueries）',
        '子查询检索（retrieve_subquery）',
      ],
    });
  });
});
