import { apiFetch } from './http';

export type ModelProvider = 'openai' | 'ollama' | 'nvidia';

export interface ProviderConfigRead {
  provider: ModelProvider;
  enabled: boolean;
  base_url: string | null;
  models: string[];
  thinking_enabled: boolean;
  thinking_level: string | null;
  api_key_set: boolean;
  api_key_masked: string | null;
  updated_at: string | null;
}

export interface ModelConfigRead {
  providers: ProviderConfigRead[];
  active_provider: ModelProvider;
  active_model: string | null;
  updated_at: string | null;
}

export interface ProviderConfigUpdate {
  enabled?: boolean;
  base_url?: string | null;
  api_key?: string | null;
  models?: string[];
  thinking_enabled?: boolean;
  thinking_level?: string | null;
}

export interface ActiveModelUpdate {
  provider: ModelProvider;
  model?: string | null;
}

export async function getModelConfig(): Promise<ModelConfigRead> {
  return apiFetch<ModelConfigRead>('/api/v1/model-config');
}

export async function updateProviderConfig(
  provider: ModelProvider,
  payload: ProviderConfigUpdate
): Promise<ModelConfigRead> {
  return apiFetch<ModelConfigRead>(`/api/v1/model-config/providers/${provider}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function updateActiveModel(payload: ActiveModelUpdate): Promise<ModelConfigRead> {
  return apiFetch<ModelConfigRead>('/api/v1/model-config/active', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}
