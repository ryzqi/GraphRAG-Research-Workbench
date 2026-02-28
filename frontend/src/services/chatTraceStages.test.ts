import { describe, expect, it } from 'vitest';

import { buildTraceStages } from './chatTraceStages';

describe('chatTraceStages', () => {
  it('aggregates runtime nodes into seven flowchart stages', () => {
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

    expect(stages).toHaveLength(7);
    expect(stages.map((stage) => stage.id)).toEqual([
      'stage_1_preprocess',
      'stage_2_route',
      'stage_3_enhance',
      'stage_4_retrieve',
      'stage_5_gate',
      'stage_6_answer',
      'stage_7_finalize',
    ]);
    expect(stages[0]?.status).toBe('completed');
    expect(stages[2]?.status).toBe('idle');
  });
});
