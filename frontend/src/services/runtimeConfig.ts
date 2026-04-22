import { apiFetch, apiV1Path, type ApiFetchOptions } from './http';
import type { ModelProvider } from './modelConfig';
import type { KbChatConfig, KbChatConfigConstraints } from './chats';
import type {
  IndexConfig,
  IndexConfigConstraints,
  KnowledgeBaseFormConstraints,
} from './knowledgeBases';

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

export interface IngestionManifestConstraintsRead {
  max_entries: number;
  max_text_length: number;
  max_url_entries: number;
  max_file_entries: number;
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
  kb_chat_default_config: KbChatConfig;
  kb_chat_config_constraints: KbChatConfigConstraints;
  knowledge_base_default_index_config: IndexConfig;
  knowledge_base_index_config_constraints: IndexConfigConstraints;
  knowledge_base_form_constraints: KnowledgeBaseFormConstraints;
  ingestion_manifest_constraints: IngestionManifestConstraintsRead;
  upload_max_file_size_bytes: number;
  upload_allowed_extensions: string[];
  upload_allowed_mime_types: string[];
  upload_mime_type_aliases: Record<string, string>;
  upload_generic_mime_types: string[];
  providers: ProviderDescriptorRead[];
}

export async function getPublicRuntimeConfig(
  options?: ApiFetchOptions
): Promise<PublicRuntimeConfigRead> {
  return apiFetch<PublicRuntimeConfigRead>(apiV1Path('/system/runtime-config'), options);
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
