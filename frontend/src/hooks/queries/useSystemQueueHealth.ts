import { useApiQuery } from '../../lib/swr';
import { getQueueHealth } from '../../services/system';

const KEYS = {
  all: ['system'] as const,
  queueHealth: ['system', 'queue-health'] as const,
};

export function useSystemQueueHealth(enabled: boolean) {
  return useApiQuery(
    enabled ? KEYS.queueHealth : null,
    enabled ? () => getQueueHealth() : null,
    {
      refreshInterval: enabled ? 5_000 : 0,
    }
  );
}

