import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchWithTimeout } from './http';

describe('fetchWithTimeout', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
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

    const pending = fetchWithTimeout('http://127.0.0.1:8000/api/v1/research/sessions');
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
