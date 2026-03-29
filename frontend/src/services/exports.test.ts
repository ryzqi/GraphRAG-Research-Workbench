import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_EXPORT_POLL_INTERVAL_MS,
  DEFAULT_EXPORT_POLL_MAX_ATTEMPTS,
} from '../constants/runtimeDefaults';
import { createExport, pollExportUntilDone } from './exports';
import { apiFetch } from './http';

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
}));

function makeExportJob(status: 'queued' | 'running' | 'succeeded' | 'failed') {
  return {
    id: 'export-1',
    status,
    download_url: status === 'succeeded' ? 'https://example.com/export.md' : null,
    error_message: status === 'failed' ? '导出失败' : null,
    created_at: '2026-03-17T00:00:00Z',
  };
}

describe('pollExportUntilDone', () => {
  const apiFetchMock = vi.mocked(apiFetch);

  beforeEach(() => {
    vi.useFakeTimers();
    apiFetchMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('uses the shared default polling interval while an export is still running', async () => {
    apiFetchMock
      .mockResolvedValueOnce(makeExportJob('queued'))
      .mockResolvedValueOnce(makeExportJob('running'))
      .mockResolvedValueOnce(makeExportJob('succeeded'));

    const resultPromise = pollExportUntilDone('export-1');

    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(DEFAULT_EXPORT_POLL_INTERVAL_MS);
    await vi.advanceTimersByTimeAsync(DEFAULT_EXPORT_POLL_INTERVAL_MS);

    await expect(resultPromise).resolves.toMatchObject({ status: 'succeeded' });
    expect(apiFetchMock).toHaveBeenCalledTimes(3);
    expect(apiFetchMock).toHaveBeenNthCalledWith(1, '/api/v1/exports/export-1');
  });

  it('times out after the shared default max-attempt budget is exhausted', async () => {
    apiFetchMock.mockResolvedValue(makeExportJob('running'));

    const resultPromise = pollExportUntilDone('export-1');
    const rejection = expect(resultPromise).rejects.toThrow('导出任务超时');

    await Promise.resolve();
    await vi.runAllTimersAsync();

    await rejection;
    expect(apiFetchMock).toHaveBeenCalledTimes(DEFAULT_EXPORT_POLL_MAX_ATTEMPTS);
  });
});

describe('createExport', () => {
  const apiFetchMock = vi.mocked(apiFetch);

  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue(makeExportJob('queued'));
  });

  it('sends session_id for research exports', async () => {
    await createExport({ type: 'research', session_id: 'session-1' });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/exports', {
      method: 'POST',
      body: JSON.stringify({
        type: 'research',
        session_id: 'session-1',
      }),
    });
  });
});
