import { afterEach, describe, expect, it, vi } from 'vitest';

describe('openSseStream', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    vi.resetModules();
  });

  it('uses same-origin stream urls in the browser and does not mention hardcoded dev loopback in errors', async () => {
    vi.stubGlobal('window', {});
    const fetchMock = vi.fn().mockRejectedValue(new Error('network down'));
    vi.stubGlobal('fetch', fetchMock);

    const { openSseStream } = await import('./sse');

    await expect(openSseStream('/api/v1/ingestion-batches/batch-1/stream')).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof Error &&
        error.message.includes('同源') &&
        !error.message.includes('127.0.0.1')
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/ingestion-batches/batch-1/stream',
      expect.objectContaining({
        headers: expect.any(Headers),
      })
    );
  });
});
