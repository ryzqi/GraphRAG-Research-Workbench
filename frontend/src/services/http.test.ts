import { afterEach, describe, expect, it, vi } from 'vitest';

import { HttpError, apiFetch } from './http';

type FetchCall = [input: string, init?: RequestInit];

function makeAbortError(): Error {
  const err = new Error('The operation was aborted');
  (err as Error & { name: string }).name = 'AbortError';
  return err;
}

describe('apiFetch error hints', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('maps 408 timeout to backend timeout hint', async () => {
    const fetchMock = vi.fn<(...args: FetchCall) => Promise<Response>>((_input, init) => {
      return new Promise((_resolve, reject) => {
        const signal = init?.signal;
        if (!signal) {
          return;
        }
        if (signal.aborted) {
          reject(makeAbortError());
          return;
        }
        signal.addEventListener(
          'abort',
          () => {
            reject(makeAbortError());
          },
          { once: true }
        );
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    let error: unknown;
    try {
      await apiFetch('/api/v1/test-timeout', { timeoutMs: 5 });
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(408);
    expect((error as HttpError).message).toContain('请求超时（后端慢/依赖慢）');
    expect((error as HttpError).message).not.toContain('无法连接到后端服务');
  });

  it('keeps connectivity hint for status 0 network failures', async () => {
    const fetchMock = vi
      .fn<(...args: FetchCall) => Promise<Response>>()
      .mockRejectedValue(new Error('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    let error: unknown;
    try {
      await apiFetch('/api/v1/test-network');
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(0);
    expect((error as HttpError).message).toContain('无法连接到后端服务');
  });
});
