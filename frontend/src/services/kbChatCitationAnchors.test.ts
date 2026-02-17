import { describe, expect, it } from 'vitest';

import { buildCitationAnchorId, normalizeCitationAnchorScopeId } from './kbChatCitationAnchors';

describe('kbChatCitationAnchors', () => {
  it('keeps legacy anchor format when scope is missing', () => {
    expect(buildCitationAnchorId('S1')).toBe('cite-S1');
  });

  it('builds unique anchors for the same citation across different assistant messages', () => {
    const first = buildCitationAnchorId('S1', 'assistant-1');
    const second = buildCitationAnchorId('S1', 'assistant-2');

    expect(first).toBe('cite-assistant-1-S1');
    expect(second).toBe('cite-assistant-2-S1');
    expect(second).not.toBe(first);
  });

  it('normalizes unsafe scope id characters', () => {
    expect(normalizeCitationAnchorScopeId(' assistant 1/# ')).toBe('assistant-1');
  });
});
