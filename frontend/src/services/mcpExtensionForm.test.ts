import { describe, expect, it } from 'vitest';

import {
  buildExtensionPayloadFromForm,
  importSingleMcpServerToFormState,
} from './mcpExtensionForm';

describe('mcpExtensionForm', () => {
  it('builds direct stdio payload without template indirection', () => {
    const payload = buildExtensionPayloadFromForm({
      name: 'Sequential Thinking',
      transport: 'stdio',
      emitMetrics: true,
      logLevelOverride: '',
      httpUrl: '',
      httpTimeoutSeconds: '',
      httpAuthType: 'none',
      httpAuthToken: '',
      httpHeadersJson: '',
      stdioCommand: 'npx',
      stdioArgsText: '-y\n@modelcontextprotocol/server-sequential-thinking',
      stdioEnvJson: '{"MCP_MODE":"prod"}',
      stdioWorkingDirectory: 'C:\\Tools\\mcp',
      stdioTimeoutSeconds: '45',
    });

    expect(payload.stdio_config).toEqual({
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-sequential-thinking'],
      env: { MCP_MODE: 'prod' },
      cwd: 'C:\\Tools\\mcp',
      timeout_seconds: 45,
    });
    expect(payload.http_config).toBeNull();
  });

  it('imports a single remote mcpServers entry into http form state', () => {
    const imported = importSingleMcpServerToFormState(`{
      "mcpServers": {
        "langchain-docs": {
          "url": "https://docs.langchain.com/mcp",
          "headers": {
            "X-Trace-Source": "codex"
          }
        }
      }
    }`);

    expect(imported.name).toBe('langchain-docs');
    expect(imported.transport).toBe('http');
    expect(imported.httpUrl).toBe('https://docs.langchain.com/mcp');
    expect(imported.httpHeadersJson).toContain('"X-Trace-Source": "codex"');
  });

  it('imports a single stdio mcpServers entry into direct command form state', () => {
    const imported = importSingleMcpServerToFormState(`{
      "mcpServers": {
        "sequential-thinking": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
          "env": {
            "MCP_MODE": "prod"
          }
        }
      }
    }`);

    expect(imported.name).toBe('sequential-thinking');
    expect(imported.transport).toBe('stdio');
    expect(imported.stdioCommand).toBe('npx');
    expect(imported.stdioArgsText).toBe('-y\n@modelcontextprotocol/server-sequential-thinking');
    expect(imported.stdioEnvJson).toContain('"MCP_MODE": "prod"');
  });
});
