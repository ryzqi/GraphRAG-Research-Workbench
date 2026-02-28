import { describe, expect, it } from 'vitest';

import {
  buildGeneralChatRecentTitle,
  shouldSkipGeneralChatHydration,
} from './generalChatSessionBehavior';

describe('generalChatSessionBehavior', () => {
  it('uses trimmed user content as recent title and truncates to 30 chars', () => {
    const title = buildGeneralChatRecentTitle('   012345678901234567890123456789ABCDE   ');
    expect(title).toBe('012345678901234567890123456789');
  });

  it('falls back to default title when content is blank', () => {
    expect(buildGeneralChatRecentTitle('    ')).toBe('普通对话');
  });

  it('skips one hydration round for a just-created session', () => {
    expect(shouldSkipGeneralChatHydration('session-1', 'session-1')).toBe(true);
    expect(shouldSkipGeneralChatHydration('session-1', 'session-2')).toBe(false);
    expect(shouldSkipGeneralChatHydration(null, 'session-1')).toBe(false);
    expect(shouldSkipGeneralChatHydration('session-1', null)).toBe(false);
  });
});
