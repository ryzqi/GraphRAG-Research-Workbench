import { describe, expect, it } from 'vitest';

import { apiV1Path, normalizeApiBaseUrl } from './http';

describe('http', () => {
  it('prefixes relative api paths with /api/v1', () => {
    expect(apiV1Path('/system/runtime-config')).toBe('/api/v1/system/runtime-config');
    expect(apiV1Path('system/runtime-config')).toBe('/api/v1/system/runtime-config');
  });

  it('does not duplicate /api/v1 when path is already versioned', () => {
    expect(apiV1Path('/api/v1/exports/export-1/download')).toBe(
      '/api/v1/exports/export-1/download'
    );
  });

  it('normalizes configured api base urls by stripping the versioned suffix', () => {
    expect(normalizeApiBaseUrl('http://127.0.0.1:8000/api/v1')).toBe('http://127.0.0.1:8000');
  });
});
