import { apiFetch, type ApiFetchOptions } from './http';
import type { ModelProvider } from './modelConfig';

export interface ProviderDescriptorRead {
  provider: ModelProvider;
  label: string;
  base_url_placeholder: string;
  base_url_helper_text: string | null;
  supports_thinking_toggle: boolean;
  supports_thinking_level: boolean;
  default_thinking_enabled: boolean;
  default_thinking_level: string | null;
  api_key_optional: boolean;
  structured_output_method: string | null;
}

export interface PublicRuntimeConfigRead {
  default_model_provider: ModelProvider;
  status_polling_interval_ms: number;
  ingestion_stream_fallback_polling_steps_ms: number[];
  ingestion_stream_retry_multiplier: number;
  export_poll_interval_ms: number;
  export_poll_max_attempts: number;
  server_prefetch_cache_revalidate_seconds: number;
  download_allowed_hosts: string[];
  providers: ProviderDescriptorRead[];
}

export async function getPublicRuntimeConfig(
  options?: ApiFetchOptions
): Promise<PublicRuntimeConfigRead> {
  return apiFetch<PublicRuntimeConfigRead>('/api/v1/system/runtime-config', options);
}

export function indexProviderDescriptors(
  descriptors: ProviderDescriptorRead[]
): Partial<Record<ModelProvider, ProviderDescriptorRead>> {
  const indexed: Partial<Record<ModelProvider, ProviderDescriptorRead>> = {};
  for (const descriptor of descriptors) {
    indexed[descriptor.provider] = descriptor;
  }
  return indexed;
}
