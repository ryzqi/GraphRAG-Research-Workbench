/**
 * 安全轮询 Hook
 * 自动处理组件卸载时的清理，防止内存泄漏
 */
import { useCallback, useEffect, useRef } from 'react';

interface UsePollingOptions<T> {
  /** 是否启用轮询 */
  enabled: boolean;
  /** 轮询间隔（毫秒） */
  interval?: number;
  /** 成功回调 */
  onSuccess?: (data: T) => void;
  /** 错误回调 */
  onError?: (error: Error) => void;
  /** 是否继续轮询（返回 false 停止） */
  shouldContinue?: (data: T) => boolean;
}

export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  options: UsePollingOptions<T>
) {
  const { enabled, interval = 2000, onSuccess, onError, shouldContinue } = options;
  const abortControllerRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);

  const poll = useCallback(async () => {
    if (!isMountedRef.current) return;

    // 取消之前的请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      const data = await fetcher(abortControllerRef.current.signal);

      if (!isMountedRef.current) return;

      onSuccess?.(data);

      // 检查是否需要继续轮询
      const shouldKeepPolling = shouldContinue ? shouldContinue(data) : true;
      if (shouldKeepPolling && isMountedRef.current) {
        timeoutRef.current = setTimeout(poll, interval);
      }
    } catch (error) {
      if (!isMountedRef.current) return;

      if (error instanceof Error && error.name === 'AbortError') {
        // 请求被取消，忽略
        return;
      }

      onError?.(error as Error);
    }
  }, [fetcher, interval, onSuccess, onError, shouldContinue]);

  useEffect(() => {
    isMountedRef.current = true;

    if (enabled) {
      poll();
    }

    return () => {
      isMountedRef.current = false;

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, [enabled, poll]);

  // 手动触发轮询
  const trigger = useCallback(() => {
    if (isMountedRef.current) {
      poll();
    }
  }, [poll]);

  // 停止轮询
  const stop = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  return { trigger, stop };
}
