/**
 * 轮询工具，支持指数退避。
 */

export interface PollingOptions {
  initialInterval?: number;
  maxInterval?: number;
  backoffFactor?: number;
  maxAttempts?: number;
}

const DEFAULT_OPTIONS: Required<PollingOptions> = {
  initialInterval: 1000,
  maxInterval: 30000,
  backoffFactor: 1.5,
  maxAttempts: 60,
};

/**
 * 使用指数退避策略轮询直到条件满足。
 */
export async function pollWithBackoff<T>(
  fn: () => Promise<T>,
  isDone: (result: T) => boolean,
  options: PollingOptions = {}
): Promise<T> {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  let interval = opts.initialInterval;
  let attempts = 0;

  while (attempts < opts.maxAttempts) {
    const result = await fn();
    if (isDone(result)) {
      return result;
    }

    attempts++;
    await new Promise((resolve) => setTimeout(resolve, interval));
    interval = Math.min(interval * opts.backoffFactor, opts.maxInterval);
  }

  throw new Error('轮询超时');
}
