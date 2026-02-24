import { describe, expect, it } from 'vitest';

import {
  ChatSessionRequestControl,
  buildChatSessionRequestKey,
} from './chatSessionRequestControl';

describe('buildChatSessionRequestKey', () => {
  it('returns null when session id is empty', () => {
    expect(buildChatSessionRequestKey({ scope: 'general', sessionId: null })).toBeNull();
  });

  it('builds a stable key from session and context', () => {
    const first = buildChatSessionRequestKey({
      scope: 'kb',
      sessionId: 'session-1',
      contextId: 'kb-a,kb-b',
    });
    const second = buildChatSessionRequestKey({
      scope: 'kb',
      sessionId: 'session-1',
      contextId: 'kb-a,kb-b',
    });

    expect(first).toBe('kb::session-1::kb-a,kb-b');
    expect(second).toBe(first);
  });
});

describe('ChatSessionRequestControl', () => {
  it('cancels previous request when quickly switching sessions', () => {
    const control = new ChatSessionRequestControl();
    const first = control.start('general::session-1::-');
    const second = control.start('general::session-2::-');

    expect(first.signal.aborted).toBe(true);
    expect(control.isLatest(first.id, 'general::session-1::-')).toBe(false);
    expect(control.isLatest(second.id, 'general::session-2::-')).toBe(true);
  });

  it('marks active request stale after page unload cancellation', () => {
    const control = new ChatSessionRequestControl();
    const request = control.start('kb::session-9::kb-1');

    control.cancelActive();

    expect(request.signal.aborted).toBe(true);
    expect(control.isLatest(request.id, 'kb::session-9::kb-1')).toBe(false);
  });
});
