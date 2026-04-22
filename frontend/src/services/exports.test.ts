import { describe, expect, it, vi } from 'vitest';

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
  apiV1Path: vi.fn((path: string) => `/api/v1${path}`),
  buildApiRequestUrl: vi.fn((path: string) => `http://127.0.0.1:8000${path}`),
}));

import { resolveExportDownloadUrl } from './exports';

describe('exports', () => {
  it('resolves relative download url against backend api base', () => {
    expect(resolveExportDownloadUrl('/api/v1/exports/export-1/download')).toBe(
      'http://127.0.0.1:8000/api/v1/exports/export-1/download'
    );
  });

  it('preserves absolute download url', () => {
    expect(resolveExportDownloadUrl('https://files.example.com/report.pdf')).toBe(
      'https://files.example.com/report.pdf'
    );
  });
});
