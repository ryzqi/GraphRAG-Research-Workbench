import { describe, expect, it } from 'vitest';

import {
  DEFAULT_EXPORT_POLL_INTERVAL_MS,
  getExportPollIntervalMs,
} from '../constants/runtimeDefaults';

describe('runtimeDefaults', () => {
  it('uses the updated export polling fallback', () => {
    expect(DEFAULT_EXPORT_POLL_INTERVAL_MS).toBe(2000);
    expect(getExportPollIntervalMs()).toBe(2000);
  });
});
