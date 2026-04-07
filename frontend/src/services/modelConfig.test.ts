import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  updateActiveModel,
  updateProviderConfig,
  type ActiveModelUpdate,
  type ProviderConfigUpdate,
} from './modelConfig';
import { apiFetch } from './http';

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
}));

describe('modelConfig service timeout policy', () => {
  const apiFetchMock = vi.mocked(apiFetch);

  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({} as never);
  });

  it('does not set request timeout when switching active Ollama model', async () => {
    const payload: ActiveModelUpdate = { provider: 'ollama', model: 'gemma4:e2b' };

    await updateActiveModel(payload);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/model-config/active', {
      method: 'PUT',
      body: JSON.stringify(payload),
      timeoutMs: 0,
    });
  });

  it('keeps default timeout when switching non-Ollama active model', async () => {
    const payload: ActiveModelUpdate = { provider: 'openai', model: 'gpt-4.1' };

    await updateActiveModel(payload);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/model-config/active', {
      method: 'PUT',
      body: JSON.stringify(payload),
      timeoutMs: 0,
    });
  });

  it('does not set request timeout when updating Ollama provider config', async () => {
    const payload: ProviderConfigUpdate = { models: ['gemma4:e2b'] };

    await updateProviderConfig('ollama', payload);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/model-config/providers/ollama', {
      method: 'PUT',
      body: JSON.stringify(payload),
      timeoutMs: 0,
    });
  });

  it('keeps default timeout when updating non-Ollama provider config', async () => {
    const payload: ProviderConfigUpdate = { models: ['gpt-4.1'] };

    await updateProviderConfig('openai', payload);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/model-config/providers/openai', {
      method: 'PUT',
      body: JSON.stringify(payload),
      timeoutMs: 0,
    });
  });

  it('does not set request timeout when switching NVIDIA active model', async () => {
    const payload: ActiveModelUpdate = { provider: 'nvidia', model: 'llama-3.1-nemotron-ultra-253b-v1' };

    await updateActiveModel(payload);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/model-config/active', {
      method: 'PUT',
      body: JSON.stringify(payload),
      timeoutMs: 0,
    });
  });

  it('does not set request timeout when updating NVIDIA provider config', async () => {
    const payload: ProviderConfigUpdate = { models: ['llama-3.1-nemotron-ultra-253b-v1'] };

    await updateProviderConfig('nvidia', payload);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/model-config/providers/nvidia', {
      method: 'PUT',
      body: JSON.stringify(payload),
      timeoutMs: 0,
    });
  });
});
