import { describe, expect, it } from 'vitest';

import { buildTraceStages } from './chatTraceStages';

describe('chatTraceStages', () => {
  it('includes runtime nodes that are missing from schema', () => {
    const stages = buildTraceStages({
      schema: {
        version: '1.0',
        nodes: [{ id: 'prepare_messages', label: '消息整理', phase: null, order: 1 }],
        edges: [],
      },
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'rewrite_branch_retrieve',
          node_name: 'rewrite_branch_retrieve',
          phase: 'end',
          ts: '2026-01-01T00:00:00.000Z',
        },
      ],
    });

    expect(stages.map((stage) => stage.id)).toEqual([
      'prepare_messages',
      'rewrite_branch_retrieve',
    ]);
  });
});
