import { describe, expect, it } from 'vitest';

import { createMessageState } from '../lib/deltaParser';
import { applyMessagesEventToState, extractDeltasFromMessagesEvent } from './chatStreamDeltas';

describe('extractDeltasFromMessagesEvent', () => {
  it('extracts structured deltas from messages payload', () => {
    const deltas = extractDeltasFromMessagesEvent({
      deltas: [
        { kind: 'thinking', content: 'thought-1' },
        { kind: 'answer', content: 'answer-1' },
      ],
    });

    expect(deltas).toHaveLength(2);
    expect(deltas[0]).toMatchObject({ kind: 'thinking', content: 'thought-1' });
    expect(deltas[1]).toMatchObject({ kind: 'answer', content: 'answer-1' });
  });
});

describe('applyMessagesEventToState', () => {
  it('accumulates thinking and answer content from messages events', () => {
    let state = createMessageState();
    state = applyMessagesEventToState(state, {
      deltas: [{ kind: 'thinking', content: 'first-thought' }],
    });
    state = applyMessagesEventToState(state, {
      deltas: [{ kind: 'answer', content: 'final-answer' }],
    });

    expect(state.thought_log).toBe('first-thought');
    expect(state.final_content).toBe('final-answer');
  });
});
