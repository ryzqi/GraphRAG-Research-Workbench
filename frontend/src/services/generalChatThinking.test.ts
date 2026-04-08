import { describe, expect, it } from 'vitest';

import {
  createStreamingAssistantMessage,
  restartStreamingAssistantMessage,
} from './generalChatThinking';

describe('generalChatThinking', () => {
  it('creates a streaming assistant message with thinkStartTime for timer rendering', () => {
    expect(createStreamingAssistantMessage('assistant-1', 1_234_567_890)).toEqual({
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      think: '',
      isStreaming: true,
      thinkStartTime: 1_234_567_890,
    });
  });

  it('restarts an existing assistant message with a fresh thinkStartTime', () => {
    expect(
      restartStreamingAssistantMessage(
        {
          id: 'assistant-1',
          role: 'assistant',
          content: '等待审批后继续',
          think: '旧思考',
          isStreaming: false,
          thinkStartTime: 100,
        },
        200
      )
    ).toMatchObject({
      id: 'assistant-1',
      role: 'assistant',
      content: '等待审批后继续',
      think: '旧思考',
      isStreaming: true,
      thinkStartTime: 200,
    });
  });
});
