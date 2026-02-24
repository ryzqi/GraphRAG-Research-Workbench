import { unstable_serialize, type Key } from 'swr';

export type SWRFallback = Record<string, unknown>;

export function appendSWRFallback(
  fallback: SWRFallback,
  key: Key,
  value: unknown
): SWRFallback {
  fallback[unstable_serialize(key)] = value;
  return fallback;
}
