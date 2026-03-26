import { describe, expect, it } from 'vitest';

import { resolveGeneralChatFinalContent } from './generalChatFinalContent';

describe('generalChatFinalContent', () => {
  it('prefers backend final content when final event includes appended reference urls', () => {
    expect(
      resolveGeneralChatFinalContent({
        streamedContent: '结论正文。',
        finalContent: '结论正文。\n\n参考来源\n- https://example.com/a',
      })
    ).toBe('结论正文。\n\n参考来源\n- https://example.com/a');
  });

  it('falls back to streamed content when final content is blank', () => {
    expect(
      resolveGeneralChatFinalContent({
        streamedContent: '仅流式内容',
        finalContent: '   ',
      })
    ).toBe('仅流式内容');
  });
});
