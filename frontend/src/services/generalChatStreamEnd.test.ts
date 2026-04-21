import { describe, expect, it } from 'vitest';

import { isUnexpectedStreamEnd } from './chats';

describe('general chat stream end semantics', () => {
  it('treats MCP approval interrupt as an expected stream stop', () => {
    expect(
      isUnexpectedStreamEnd({
        sawFinalEvent: false,
        sawErrorEvent: false,
        sawInterruptEvent: true,
      })
    ).toBe(false);
  });
});

