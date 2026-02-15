import { describe, expect, it } from 'vitest';

import type { ChatNodeIoEvent, KbGraphSchema } from './chats';
import { resolveFinalizeNodeIds, shouldRevealAnswerOnNodeEvent } from './kbChatAnswerReveal';

function createSchema(phases: Array<{ id: string; phase: string | null }>): KbGraphSchema {
  return {
    version: '1.0',
    nodes: phases.map((item, index) => ({
      id: item.id,
      label: item.id,
      phase: item.phase,
      order: index,
    })),
    edges: [],
  };
}

function createNodeEvent(partial: Partial<ChatNodeIoEvent>): ChatNodeIoEvent {
  return {
    run_id: 'run-1',
    node_name: 'draft',
    node_id: 'draft',
    phase: 'start',
    ts: '2026-02-15T10:00:00.000Z',
    ...partial,
  };
}

describe('resolveFinalizeNodeIds', () => {
  it('returns ids of nodes in finalize phase', () => {
    const ids = resolveFinalizeNodeIds(
      createSchema([
        { id: 'draft', phase: 'generate' },
        { id: 'finalize_answer', phase: 'finalize' },
      ])
    );

    expect([...ids]).toEqual(['finalize_answer']);
  });

  it('returns empty set when schema has no finalize nodes', () => {
    const ids = resolveFinalizeNodeIds(createSchema([{ id: 'draft', phase: 'generate' }]));

    expect(ids.size).toBe(0);
  });
});

describe('shouldRevealAnswerOnNodeEvent', () => {
  it('reveals only on finalize end event', () => {
    const finalizeIds = new Set(['finalize_answer']);

    expect(
      shouldRevealAnswerOnNodeEvent(
        createNodeEvent({ node_name: 'finalize_answer', node_id: 'finalize_answer', phase: 'end' }),
        finalizeIds
      )
    ).toBe(true);

    expect(
      shouldRevealAnswerOnNodeEvent(
        createNodeEvent({ node_name: 'finalize_answer', node_id: 'finalize_answer', phase: 'start' }),
        finalizeIds
      )
    ).toBe(false);

    expect(
      shouldRevealAnswerOnNodeEvent(
        createNodeEvent({ node_name: 'draft', node_id: 'draft', phase: 'end' }),
        finalizeIds
      )
    ).toBe(false);
  });

  it('matches node id with suffix', () => {
    const finalizeIds = new Set(['finalize_answer']);

    expect(
      shouldRevealAnswerOnNodeEvent(
        createNodeEvent({ node_name: 'finalize_answer#2', node_id: 'finalize_answer#2', phase: 'end' }),
        finalizeIds
      )
    ).toBe(true);
  });
});
