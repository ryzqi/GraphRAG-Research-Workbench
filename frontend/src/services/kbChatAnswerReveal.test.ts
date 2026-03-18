import { describe, expect, it } from 'vitest';

import { resolveFinalizeNodeIds, shouldRevealAnswerOnNodeEvent } from './kbChatAnswerReveal';

describe('kbChatAnswerReveal', () => {
  it('reveals on answer_commit and force_exit after confidence calibration removal', () => {
    const schema = {
      version: '1.1',
      hash: 'schema-hash',
      nodes: [
        {
          id: 'answer_commit',
          label: '答案提交',
          phase: 'generate',
          order: 32,
          metadata: { phase: 'generate', order: 32, label: '答案提交' },
        },
        {
          id: 'force_exit',
          label: '提前终止',
          phase: 'finalize',
          order: 33,
          metadata: { phase: 'finalize', order: 33, label: '提前终止' },
        },
      ],
      edges: [],
    };

    const terminalNodeIds = resolveFinalizeNodeIds(schema);

    expect(terminalNodeIds.has('answer_commit')).toBe(true);
    expect(terminalNodeIds.has('force_exit')).toBe(true);
    expect(terminalNodeIds.has('confidence_calibrate')).toBe(false);
    expect(
      shouldRevealAnswerOnNodeEvent(
        { phase: 'end', node_name: 'answer_commit', node_id: 'answer_commit' },
        terminalNodeIds
      )
    ).toBe(true);
    expect(
      shouldRevealAnswerOnNodeEvent(
        { phase: 'end', node_name: 'force_exit', node_id: 'force_exit' },
        terminalNodeIds
      )
    ).toBe(true);
  });

  it('does not reveal on non-terminal review nodes', () => {
    const terminalNodeIds = new Set(['answer_commit', 'force_exit']);

    expect(
      shouldRevealAnswerOnNodeEvent(
        {
          phase: 'end',
          node_name: 'answer_review_factual',
          node_id: 'answer_review_factual',
        },
        terminalNodeIds
      )
    ).toBe(false);
  });
});
