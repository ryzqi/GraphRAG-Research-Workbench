import { describe, expect, it } from 'vitest';

import {
  DEFAULT_MODEL_PROVIDER,
  createDefaultExtensionFormState,
  createDefaultModelProviderFormState,
} from './formDefaults';

describe('formDefaults', () => {
  it('creates the repo default extension form state for new extensions', () => {
    expect(createDefaultExtensionFormState('stdio-template-1')).toEqual({
      name: '',
      transport: 'http',
      emitMetrics: true,
      logLevelOverride: '',
      httpUrl: '',
      httpTimeoutSeconds: '',
      httpAuthType: 'none',
      httpAuthToken: '',
      httpHeadersJson: '',
      stdioTemplateId: 'stdio-template-1',
      stdioArgsText: '',
      stdioEnvJson: '',
      stdioTimeoutSeconds: '',
    });
  });

  it('creates isolated model-provider form state objects with the repo defaults', () => {
    const first = createDefaultModelProviderFormState();
    const second = createDefaultModelProviderFormState();

    expect(DEFAULT_MODEL_PROVIDER).toBe('openai');
    expect(first).toEqual({
      enabled: true,
      baseUrl: '',
      models: [],
      modelInput: '',
      apiKey: '',
      clearApiKey: false,
      thinkingEnabled: true,
      thinkingLevel: 'high',
    });
    expect(first).not.toBe(second);
    expect(first.models).not.toBe(second.models);
  });
});
