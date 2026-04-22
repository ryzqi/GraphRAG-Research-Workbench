import { beforeEach, describe, expect, it, vi } from 'vitest';

const getApiOriginMock = vi.fn();

vi.mock('./http', () => ({
  getApiOrigin: () => getApiOriginMock(),
}));

vi.mock('./logger', () => ({
  appLogger: {
    warn: vi.fn(),
  },
}));

import { isAllowedDownloadUrl } from '../utils/urlValidation';

describe('urlValidation', () => {
  beforeEach(() => {
    getApiOriginMock.mockReset();
  });

  it('allows backend origin even when runtime allowed hosts is empty', () => {
    getApiOriginMock.mockReturnValue('http://127.0.0.1:8000');

    expect(isAllowedDownloadUrl('http://127.0.0.1:8000/api/v1/exports/export-1/download', [])).toBe(true);
  });

  it('still blocks unrelated absolute hosts', () => {
    getApiOriginMock.mockReturnValue('http://127.0.0.1:8000');

    expect(isAllowedDownloadUrl('https://evil.example.com/file.pdf', [])).toBe(false);
  });
});
