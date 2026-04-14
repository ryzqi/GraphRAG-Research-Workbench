import { describe, expect, it } from 'vitest';

import { createDefaultExtensionFormState } from '../constants/formDefaults';
import { buildExtensionPayloadFromForm } from './mcpExtensionForm';

describe('mcpExtensionForm logging cleanup', () => {
  it('does not expose dead observability controls in default extension form state', () => {
    const defaults = createDefaultExtensionFormState();

    expect(defaults).not.toHaveProperty('emitMetrics');
    expect(defaults).not.toHaveProperty('logLevelOverride');
  });

  it('does not include observability_config in extension payloads', () => {
    const payload = buildExtensionPayloadFromForm({
      ...createDefaultExtensionFormState(),
      name: 'Docs MCP',
      transport: 'http',
      emitMetrics: true,
      logLevelOverride: 'DEBUG',
      httpUrl: 'https://mcp.example.com',
      httpTimeoutSeconds: '',
      httpAuthType: 'none',
      httpAuthToken: '',
      httpHeadersJson: '',
      stdioCommand: '',
      stdioArgsText: '',
      stdioEnvJson: '',
      stdioWorkingDirectory: '',
      stdioTimeoutSeconds: '',
    } as any);

    expect(payload).not.toHaveProperty('observability_config');
  });
});
