import { afterEach, describe, expect, it, vi } from 'vitest';

import { isAllowedDownloadUrl, safeDownloadUrl } from './urlValidation';

describe('safeDownloadUrl', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('creates a temporary anchor and clicks it for trusted download URLs', () => {
    const click = vi.fn();
    const appendChild = vi.fn();
    const removeChild = vi.fn();
    const anchor = {
      href: '',
      rel: '',
      style: { display: '' },
      click,
    };

    vi.stubGlobal('document', {
      body: {
        appendChild,
        removeChild,
      },
      createElement: vi.fn((_tag: string) => anchor),
    });

    const result = safeDownloadUrl(
      'https://downloads.internal/mkb-exports/research-report.pdf',
      ['downloads.internal']
    );

    expect(result).toBe(true);
    expect(anchor.href).toBe('https://downloads.internal/mkb-exports/research-report.pdf');
    expect(anchor.rel).toBe('noopener noreferrer');
    expect(anchor.style.display).toBe('none');
    expect(appendChild).toHaveBeenCalledWith(anchor);
    expect(click).toHaveBeenCalledTimes(1);
    expect(removeChild).toHaveBeenCalledWith(anchor);
  });

  it('rejects download URLs from untrusted domains', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const result = safeDownloadUrl('https://example.com/report.pdf', ['downloads.internal']);

    expect(result).toBe(false);
    expect(warn).toHaveBeenCalledWith(
      '下载链接来自不受信任的域名:',
      'https://example.com/report.pdf'
    );
  });

  it('allows relative download urls when the allowlist comes from runtime config', () => {
    expect(isAllowedDownloadUrl('/api/v1/exports/report.pdf', ['downloads.internal'])).toBe(true);
  });
});
