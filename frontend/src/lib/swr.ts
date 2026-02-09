import { useCallback, useMemo, useState } from 'react';
import type { Key, SWRConfiguration, SWRResponse } from 'swr';
import useSWR, { useSWRConfig } from 'swr';

export const defaultSWRConfig: SWRConfiguration = {
  revalidateOnFocus: false,
  shouldRetryOnError: true,
  errorRetryCount: 1,
  dedupingInterval: 2_000,
  focusThrottleInterval: 30_000,
  keepPreviousData: true,
};

export interface QueryResult<TData>
  extends Omit<SWRResponse<TData, Error>, 'mutate'> {
  mutate: SWRResponse<TData, Error>['mutate'];
  isPending: boolean;
  isFetching: boolean;
  refetch: () => Promise<TData | undefined>;
}

export function useApiQuery<TData>(
  key: Key,
  fetcher: (() => Promise<TData>) | null,
  config?: SWRConfiguration<TData, Error>
): QueryResult<TData> {
  const swr = useSWR<TData, Error>(key, fetcher, config);

  const refetch = useCallback(async () => {
    return swr.mutate();
  }, [swr]);

  return useMemo(
    () => ({
      ...swr,
      isPending: swr.isLoading,
      isFetching: swr.isValidating,
      refetch,
    }),
    [swr, refetch]
  );
}

interface MutationHelpers {
  invalidate: (keys: Key[]) => Promise<void>;
  setCachedData: <TData>(key: Key, data: TData) => Promise<TData | undefined>;
}

function isArrayKey(key: Key): key is readonly unknown[] {
  return Array.isArray(key);
}

function matchesArrayKeyPrefix(
  cachedKey: unknown,
  prefixKey: readonly unknown[]
): boolean {
  if (!Array.isArray(cachedKey) || cachedKey.length < prefixKey.length) {
    return false;
  }

  return prefixKey.every((segment, index) => Object.is(cachedKey[index], segment));
}

interface UseApiMutationOptions<TArg, TData> {
  onSuccess?: (data: TData, arg: TArg, helpers: MutationHelpers) => void | Promise<void>;
  onError?: (error: Error, arg: TArg) => void;
}

interface MutationCallbacks<TArg, TData> {
  onSuccess?: (data: TData, arg: TArg) => void;
  onError?: (error: Error, arg: TArg) => void;
}

export interface ApiMutationResult<TArg, TData> {
  mutateAsync: (arg: TArg) => Promise<TData>;
  mutate: (arg: TArg, callbacks?: MutationCallbacks<TArg, TData>) => void;
  isPending: boolean;
  error: Error | null;
  data: TData | undefined;
  reset: () => void;
}

export function useApiMutation<TArg, TData>(
  mutationFn: (arg: TArg) => Promise<TData>,
  options?: UseApiMutationOptions<TArg, TData>
): ApiMutationResult<TArg, TData> {
  const { mutate } = useSWRConfig();
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [data, setData] = useState<TData | undefined>(undefined);

  const invalidate = useCallback(
    async (keys: Key[]) => {
      await Promise.all(
        keys.map((key) => {
          if (!isArrayKey(key)) {
            return mutate(key);
          }

          return mutate(
            (cachedKey) => matchesArrayKeyPrefix(cachedKey, key),
            undefined,
            { revalidate: true }
          );
        })
      );
    },
    [mutate]
  );

  const setCachedData = useCallback(
    async <TCachedData,>(key: Key, nextData: TCachedData) => {
      return mutate<TCachedData>(key, nextData, { revalidate: false });
    },
    [mutate]
  );

  const mutateAsync = useCallback(
    async (arg: TArg) => {
      setIsPending(true);
      setError(null);

      try {
        const result = await mutationFn(arg);
        setData(result);
        if (options?.onSuccess) {
          await options.onSuccess(result, arg, { invalidate, setCachedData });
        }
        return result;
      } catch (caughtError) {
        const normalizedError =
          caughtError instanceof Error
            ? caughtError
            : new Error('Mutation failed');
        setError(normalizedError);
        options?.onError?.(normalizedError, arg);
        throw normalizedError;
      } finally {
        setIsPending(false);
      }
    },
    [mutationFn, options, invalidate, setCachedData]
  );

  const reset = useCallback(() => {
    setError(null);
    setData(undefined);
  }, []);

  const runMutation = useCallback(
    (arg: TArg, callbacks?: MutationCallbacks<TArg, TData>) => {
      void mutateAsync(arg)
        .then((result) => {
          callbacks?.onSuccess?.(result, arg);
        })
        .catch((caughtError) => {
          const normalizedError =
            caughtError instanceof Error
              ? caughtError
              : new Error('Mutation failed');
          callbacks?.onError?.(normalizedError, arg);
        });
    },
    [mutateAsync]
  );

  return {
    mutateAsync,
    mutate: runMutation,
    isPending,
    error,
    data,
    reset,
  };
}
