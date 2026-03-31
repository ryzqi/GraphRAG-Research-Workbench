import { describe, expect, it, vi } from 'vitest';
import {
  createKnowledgeBaseAddDocumentsFallbackPromise,
  createKnowledgeBaseDetailFallbackPromise,
  resolveSingleSearchParamValue,
} from './routePrefetch';

describe('resolveSingleSearchParamValue', () => {
  it('returns the raw value for scalar search params', () => {
    expect(resolveSingleSearchParamValue('job-1')).toBe('job-1');
  });

  it('returns the first item for array search params', () => {
    expect(resolveSingleSearchParamValue(['job-1', 'job-2'])).toBe('job-1');
  });

  it('returns undefined for missing search params', () => {
    expect(resolveSingleSearchParamValue(undefined)).toBeUndefined();
  });
});

describe('createKnowledgeBaseDetailFallbackPromise', () => {
  it('forwards the resolved kbId to the detail prefetcher', async () => {
    const prefetchFn = vi.fn().mockResolvedValue({});

    const fallback = await createKnowledgeBaseDetailFallbackPromise(
      Promise.resolve({ kbId: 'kb-1' }),
      { prefetchFn }
    );

    expect(fallback).toEqual({});
    expect(prefetchFn).toHaveBeenCalledTimes(1);
    expect(prefetchFn).toHaveBeenCalledWith('kb-1', undefined);
  });
});

describe('createKnowledgeBaseAddDocumentsFallbackPromise', () => {
  it('passes the first job id from search params to the prefetcher', async () => {
    const prefetchFn = vi.fn().mockResolvedValue({});

    const fallback = await createKnowledgeBaseAddDocumentsFallbackPromise(
      Promise.resolve({ kbId: 'kb-1' }),
      Promise.resolve({ job: ['job-1', 'job-2'] }),
      { prefetchFn }
    );

    expect(fallback).toEqual({});
    expect(prefetchFn).toHaveBeenCalledTimes(1);
    expect(prefetchFn).toHaveBeenCalledWith('kb-1', 'job-1', undefined);
  });

  it('keeps jobId undefined when search params do not contain job', async () => {
    const prefetchFn = vi.fn().mockResolvedValue({});

    await createKnowledgeBaseAddDocumentsFallbackPromise(
      Promise.resolve({ kbId: 'kb-1' }),
      Promise.resolve({}),
      { prefetchFn }
    );

    expect(prefetchFn).toHaveBeenCalledWith('kb-1', undefined, undefined);
  });
});
