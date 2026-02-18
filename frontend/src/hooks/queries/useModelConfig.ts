import { useApiMutation, useApiQuery } from '../../lib/swr';
import {
  getModelConfig,
  updateActiveModel,
  updateProviderConfig,
  type ActiveModelUpdate,
  type ModelProvider,
  type ProviderConfigUpdate,
} from '../../services/modelConfig';

const KEYS = {
  all: ['model-config'] as const,
  detail: () => [...KEYS.all, 'detail'] as const,
};

export function useModelConfig() {
  return useApiQuery(KEYS.detail(), () => getModelConfig());
}

export function useUpdateProviderConfig() {
  return useApiMutation(
    ({ provider, payload }: { provider: ModelProvider; payload: ProviderConfigUpdate }) =>
      updateProviderConfig(provider, payload),
    {
      onSuccess: async (_, __, { invalidate }) => {
        await invalidate([KEYS.detail()]);
      },
    }
  );
}

export function useUpdateActiveModel() {
  return useApiMutation((payload: ActiveModelUpdate) => updateActiveModel(payload), {
    onSuccess: async (_, __, { invalidate }) => {
      await invalidate([KEYS.detail()]);
    },
  });
}

export { KEYS as modelConfigKeys };
