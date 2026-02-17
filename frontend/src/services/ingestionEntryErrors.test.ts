import { describe, expect, it } from 'vitest';

import type { EntryError } from './ingestionBatches';
import { formatIngestionEntryError } from './ingestionEntryErrors';

function createError(overrides: Partial<EntryError> = {}): EntryError {
  return {
    entry_id: 'entry_1',
    source_type: 'url',
    code: 'URL_SSRF_BLOCKED',
    message: 'URL 被 SSRF 防护策略拦截',
    retryable: false,
    details: null,
    ...overrides,
  };
}

describe('formatIngestionEntryError', () => {
  it('keeps the original message when no structured details are available', () => {
    expect(formatIngestionEntryError(createError({ details: null }))).toBe('URL 被 SSRF 防护策略拦截');
  });

  it('appends host, blocked IP and reason for URL_SSRF_BLOCKED', () => {
    const message = formatIngestionEntryError(
      createError({
        details: {
          host: 'en.wikipedia.org',
          blocked_ips: ['127.0.0.1'],
          blocked_reason: 'private_or_local_cidr',
        },
      })
    );

    expect(message).toContain('URL 被 SSRF 防护策略拦截');
    expect(message).toContain('主机 en.wikipedia.org');
    expect(message).toContain('命中 IP 127.0.0.1');
    expect(message).toContain('private_or_local_cidr');
  });
});
