import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchWithTimeout } from './http';

describe('fetchWithTimeout', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    vi.resetModules();
  });

  it('does not apply a default timeout when timeoutMs is omitted', async () => {
    vi.useFakeTimers();

    let resolveFetch!: (response: Response) => void;

    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        return new Promise<Response>((resolve, reject) => {
          resolveFetch = resolve;
          init?.signal?.addEventListener(
            'abort',
            () => {
              const error = new Error('aborted');
              error.name = 'AbortError';
              reject(error);
            },
            { once: true }
          );
        });
      })
    );

    const pending = fetchWithTimeout('https://api.internal.example/api/v1/research/sessions');
    let outcome: 'pending' | 'resolved' | 'rejected' = 'pending';
    void pending.then(
      () => {
        outcome = 'resolved';
      },
      () => {
        outcome = 'rejected';
      }
    );

    await vi.advanceTimersByTimeAsync(31_000);

    expect(outcome).toBe('pending');

    resolveFetch(new Response('{}', { status: 200 }));
    const { response } = await pending;
    expect(response.status).toBe(200);
  });
});

describe('api base url resolution', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    vi.resetModules();
  });

  it('uses same-origin relative paths in the browser when NEXT_PUBLIC_API_BASE_URL is omitted', async () => {
    vi.stubGlobal('window', {});
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch, getApiBaseUrl } = await import('./http');
    await apiFetch('/api/v1/system/runtime-config');

    expect(getApiBaseUrl()).toBe('');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/system/runtime-config',
      expect.objectContaining({
        headers: expect.any(Headers),
      })
    );
  });

  it('removes the public api prefix from explicit base urls without rewriting the host', async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = 'https://api.internal.example/api/v1';

    const { getApiBaseUrl } = await import('./http');

    expect(getApiBaseUrl()).toBe('https://api.internal.example');
  });

  it('fails fast for server-side requests when NEXT_PUBLIC_API_BASE_URL is omitted', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('./http');

    await expect(apiFetch('/api/v1/system/runtime-config')).rejects.toMatchObject({
      name: 'HttpError',
      status: 500,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
