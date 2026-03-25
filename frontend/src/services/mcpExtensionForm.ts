import { createDefaultExtensionFormState } from '../constants/formDefaults';
import type {
  ExtensionAuthType,
  ToolExtension,
  ToolExtensionCreate,
} from './extensions';

export interface ExtensionFormState {
  name: string;
  transport: 'stdio' | 'http';
  emitMetrics: boolean;
  logLevelOverride: '' | 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

  httpUrl: string;
  httpTimeoutSeconds: string;
  httpAuthType: ExtensionAuthType;
  httpAuthToken: string;
  httpHeadersJson: string;

  stdioCommand: string;
  stdioArgsText: string;
  stdioEnvJson: string;
  stdioWorkingDirectory: string;
  stdioTimeoutSeconds: string;
}

function toOptionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error('超时时间必须为正整数');
  }
  return parsed;
}

function parseJsonRecord(text: string, fieldName: string): Record<string, string> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(`${fieldName} 必须是合法 JSON 对象`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${fieldName} 必须是 JSON 对象`);
  }
  return Object.fromEntries(Object.entries(parsed).map(([k, v]) => [String(k), String(v)]));
}

function formatJson(input: Record<string, string> | null | undefined): string {
  if (!input || Object.keys(input).length === 0) return '';
  return JSON.stringify(input, null, 2);
}

export function buildFormFromExtension(ext: ToolExtension): ExtensionFormState {
  const defaults = createDefaultExtensionFormState();
  return {
    ...defaults,
    name: ext.name,
    transport: ext.transport,
    emitMetrics: ext.observability_config?.emit_metrics ?? defaults.emitMetrics,
    logLevelOverride: ext.observability_config?.log_level_override ?? defaults.logLevelOverride,

    httpUrl: ext.http_config?.url ?? defaults.httpUrl,
    httpTimeoutSeconds:
      ext.http_config?.timeout_seconds !== null &&
      ext.http_config?.timeout_seconds !== undefined
        ? String(ext.http_config.timeout_seconds)
        : defaults.httpTimeoutSeconds,
    httpAuthType: ext.http_config?.auth?.type ?? defaults.httpAuthType,
    httpAuthToken: ext.http_config?.auth?.token ?? defaults.httpAuthToken,
    httpHeadersJson: formatJson(ext.http_config?.headers ?? null),

    stdioCommand: ext.stdio_config?.command ?? defaults.stdioCommand,
    stdioArgsText: (ext.stdio_config?.args ?? []).join('\n'),
    stdioEnvJson: formatJson(ext.stdio_config?.env ?? null),
    stdioWorkingDirectory: ext.stdio_config?.cwd ?? defaults.stdioWorkingDirectory,
    stdioTimeoutSeconds:
      ext.stdio_config?.timeout_seconds !== null &&
      ext.stdio_config?.timeout_seconds !== undefined
        ? String(ext.stdio_config.timeout_seconds)
        : defaults.stdioTimeoutSeconds,
  };
}

export function buildExtensionPayloadFromForm(form: ExtensionFormState): ToolExtensionCreate {
  const payload: ToolExtensionCreate = {
    name: form.name.trim(),
    transport: form.transport,
    observability_config: {
      emit_metrics: form.emitMetrics,
      ...(form.logLevelOverride ? { log_level_override: form.logLevelOverride } : {}),
    },
  };

  if (!payload.name) {
    throw new Error('扩展名称不能为空');
  }

  if (form.transport === 'http') {
    const timeout = toOptionalNumber(form.httpTimeoutSeconds);
    const headers = parseJsonRecord(form.httpHeadersJson, 'HTTP Headers');
    const token = form.httpAuthToken.trim();
    payload.http_config = {
      url: form.httpUrl.trim(),
      protocol: 'streamable_http',
      headers,
      auth: {
        type: form.httpAuthType,
        ...(form.httpAuthType !== 'none' && token ? { token } : {}),
      },
      ...(timeout ? { timeout_seconds: timeout } : {}),
    };
    payload.stdio_config = null;
    return payload;
  }

  const timeout = toOptionalNumber(form.stdioTimeoutSeconds);
  const env = parseJsonRecord(form.stdioEnvJson, 'STDIO 环境变量');
  const command = form.stdioCommand.trim();
  if (!command) {
    throw new Error('STDIO 命令不能为空');
  }
  const cwd = form.stdioWorkingDirectory.trim();
  payload.stdio_config = {
    command,
    args: form.stdioArgsText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    env,
    ...(cwd ? { cwd } : {}),
    ...(timeout ? { timeout_seconds: timeout } : {}),
  };
  payload.http_config = null;
  return payload;
}

function assertRecord(value: unknown, fieldName: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${fieldName} 必须是对象`);
  }
  return value as Record<string, unknown>;
}

export function importSingleMcpServerToFormState(text: string): ExtensionFormState {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error('导入内容必须是合法 JSON');
  }

  const root = assertRecord(parsed, '导入根对象');
  const servers = assertRecord(root.mcpServers, 'mcpServers');
  const names = Object.keys(servers);
  if (names.length !== 1) {
    throw new Error('当前仅支持一次导入 1 个 MCP server');
  }

  const name = names[0];
  const rawConfig = assertRecord(servers[name], `mcpServers.${name}`);
  const defaults = createDefaultExtensionFormState();

  if (typeof rawConfig.url === 'string' && rawConfig.url.trim()) {
    const headers =
      rawConfig.headers && typeof rawConfig.headers === 'object' && !Array.isArray(rawConfig.headers)
        ? (rawConfig.headers as Record<string, unknown>)
        : {};
    return {
      ...defaults,
      name,
      transport: 'http',
      httpUrl: rawConfig.url.trim(),
      httpHeadersJson: formatJson(
        Object.fromEntries(Object.entries(headers).map(([k, v]) => [k, String(v)]))
      ),
    };
  }

  if (typeof rawConfig.command === 'string' && rawConfig.command.trim()) {
    const rawArgs = Array.isArray(rawConfig.args) ? rawConfig.args : [];
    const rawEnv =
      rawConfig.env && typeof rawConfig.env === 'object' && !Array.isArray(rawConfig.env)
        ? (rawConfig.env as Record<string, unknown>)
        : {};
    return {
      ...defaults,
      name,
      transport: 'stdio',
      stdioCommand: rawConfig.command.trim(),
      stdioArgsText: rawArgs.map((item) => String(item)).join('\n'),
      stdioEnvJson: formatJson(
        Object.fromEntries(Object.entries(rawEnv).map(([k, v]) => [k, String(v)]))
      ),
      stdioWorkingDirectory:
        typeof rawConfig.cwd === 'string' ? rawConfig.cwd.trim() : defaults.stdioWorkingDirectory,
    };
  }

  throw new Error('导入的 MCP server 必须包含 url 或 command');
}
