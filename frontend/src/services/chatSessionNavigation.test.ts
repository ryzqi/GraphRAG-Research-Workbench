import { describe, expect, it } from 'vitest';

import {
  resolveDeletedSessionNavigationTarget,
  shouldResetChatStateOnSessionClear,
} from './chatSessionNavigation';

describe('chatSessionNavigation', () => {
  it('navigates back to the current chat route when the user deletes the active recent session', () => {
    expect(
      resolveDeletedSessionNavigationTarget({
        pathname: '/kb-chat',
        currentSessionId: 'session-1',
        deletedSessionId: 'session-1',
        deletedSessionType: 'kb_chat',
      })
    ).toBe('/kb-chat');
  });

  it('does not change route when deleting a non-active recent session', () => {
    expect(
      resolveDeletedSessionNavigationTarget({
        pathname: '/kb-chat',
        currentSessionId: 'session-1',
        deletedSessionId: 'session-2',
        deletedSessionType: 'kb_chat',
      })
    ).toBeNull();
  });

  it('does not change route when the current page and deleted session type do not match', () => {
    expect(
      resolveDeletedSessionNavigationTarget({
        pathname: '/general-chat',
        currentSessionId: 'session-1',
        deletedSessionId: 'session-1',
        deletedSessionType: 'kb_chat',
      })
    ).toBeNull();
  });

  it('treats removing sessionId from the route as a reset signal for local chat state', () => {
    expect(shouldResetChatStateOnSessionClear('session-1', null)).toBe(true);
    expect(shouldResetChatStateOnSessionClear('session-1', 'session-2')).toBe(false);
    expect(shouldResetChatStateOnSessionClear(null, null)).toBe(false);
  });
});
