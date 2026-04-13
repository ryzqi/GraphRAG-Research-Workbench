import { afterEach, describe, expect, it, vi } from 'vitest';

import { getPublicRuntimeConfig, indexProviderDescriptors } from './runtimeConfig';

const { apiFetchMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
}));

vi.mock('./http', () => ({
  apiFetch: apiFetchMock,
}));

describe('runtimeConfig service', () => {
  afterEach(() => {
    apiFetchMock.mockReset();
  });

  it('loads provider descriptors from the public runtime config endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      default_model_provider: 'openai',
      status_polling_interval_ms: 2000,
      ingestion_stream_fallback_polling_steps_ms: [1000, 2000, 5000],
      ingestion_stream_retry_multiplier: 2,
      export_poll_interval_ms: 1000,
      export_poll_max_attempts: 60,
      server_prefetch_cache_revalidate_seconds: 30,
      download_allowed_hosts: [],
      providers: [
        {
          provider: 'openai',
          label: 'OpenAI',
          base_url_placeholder: 'https://api.openai.com/v1',
          base_url_helper_text: null,
          supports_thinking_toggle: true,
          supports_thinking_level: true,
          default_thinking_enabled: true,
          default_thinking_level: 'high',
          api_key_optional: false,
          structured_output_method: 'responses',
        },
      ],
    });

    const config = await getPublicRuntimeConfig();

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/system/runtime-config', undefined);
    expect(config.status_polling_interval_ms).toBe(2000);
    expect(config.download_allowed_hosts).toEqual([]);
    expect(config.providers[0]?.label).toBe('OpenAI');
  });

  it('indexes provider descriptors by provider id', () => {
    const descriptors = indexProviderDescriptors([
      {
        provider: 'openai',
        label: 'OpenAI',
        base_url_placeholder: 'https://api.openai.com/v1',
        base_url_helper_text: null,
        supports_thinking_toggle: true,
        supports_thinking_level: true,
        default_thinking_enabled: true,
        default_thinking_level: 'high',
        api_key_optional: false,
        structured_output_method: 'responses',
      },
      {
        provider: 'llama.cpp',
        label: 'llama.cpp',
        base_url_placeholder: 'http://<llama-cpp-host>:8080/v1',
        base_url_helper_text: 'helper',
        supports_thinking_toggle: false,
        supports_thinking_level: false,
        default_thinking_enabled: false,
        default_thinking_level: null,
        api_key_optional: true,
        structured_output_method: null,
      },
    ]);

    expect(descriptors['openai']?.label).toBe('OpenAI');
    expect(descriptors['llama.cpp']?.supports_thinking_toggle).toBe(false);
  });
});
