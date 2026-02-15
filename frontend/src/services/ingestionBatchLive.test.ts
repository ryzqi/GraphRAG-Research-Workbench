import { describe, expect, it } from 'vitest';

import { shouldFallbackAfterStreamExit } from '../hooks/queries/useIngestionBatches';

describe('shouldFallbackAfterStreamExit', () => {
  it('returns true when stream exits without final event', () => {
    expect(
      shouldFallbackAfterStreamExit({
        active: true,
        aborted: false,
        receivedFinal: false,
      })
    ).toBe(true);
  });

  it('returns false when final event was received', () => {
    expect(
      shouldFallbackAfterStreamExit({
        active: true,
        aborted: false,
        receivedFinal: true,
      })
    ).toBe(false);
  });

  it('returns false when stream was aborted', () => {
    expect(
      shouldFallbackAfterStreamExit({
        active: true,
        aborted: true,
        receivedFinal: false,
      })
    ).toBe(false);
  });

  it('returns false when effect is no longer active', () => {
    expect(
      shouldFallbackAfterStreamExit({
        active: false,
        aborted: false,
        receivedFinal: false,
      })
    ).toBe(false);
  });
});
