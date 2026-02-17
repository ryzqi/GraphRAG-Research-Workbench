import { describe, expect, it } from 'vitest';

import { resolveActiveAssistantId } from './kbChatAssistantSelection';

describe('resolveActiveAssistantId', () => {
  it('returns null when there are no assistant messages', () => {
    expect(resolveActiveAssistantId([], null)).toBeNull();
  });

  it('falls back to latest message when active id is missing', () => {
    expect(
      resolveActiveAssistantId(
        [
          { id: 'assistant-1', isStreaming: false },
          { id: 'assistant-2', isStreaming: false },
        ],
        'assistant-not-exist'
      )
    ).toBe('assistant-2');
  });

  it('keeps current selection when it still exists and no new streaming message appears', () => {
    expect(
      resolveActiveAssistantId(
        [
          { id: 'assistant-1', isStreaming: false },
          { id: 'assistant-2', isStreaming: false },
        ],
        'assistant-1'
      )
    ).toBe('assistant-1');
  });

  it('switches to latest assistant when a new round starts streaming', () => {
    expect(
      resolveActiveAssistantId(
        [
          { id: 'assistant-1', isStreaming: false },
          { id: 'assistant-2', isStreaming: true },
        ],
        'assistant-1'
      )
    ).toBe('assistant-2');
  });
});
