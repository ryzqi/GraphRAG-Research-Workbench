import { useApiQuery } from '../../lib/swr';
import { getPublicRuntimeConfig } from '../../services/runtimeConfig';

const KEYS = {
  all: ['runtime-config'] as const,
  detail: () => [...KEYS.all, 'detail'] as const,
};

export function useRuntimeConfig() {
  return useApiQuery(KEYS.detail(), () => getPublicRuntimeConfig());
}

export { KEYS as runtimeConfigKeys };
