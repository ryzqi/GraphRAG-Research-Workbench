/**
 * 运行时真实生效的前端表单默认值。
 *
 * 这些值不是框架默认，而是仓库当前的产品默认：
 * - Model Config：新 provider 先以“启用 + 开启思考 + high”展示，降低首次配置门槛；
 * - Extensions：新扩展编辑器默认走 HTTP、开启 metrics、HTTP 鉴权默认 none。
 *
 * 通过集中工厂函数返回新对象，避免各页面复制字面量后再逐渐漂移。
 */

type ModelProviderFormDefaults = {
  default_thinking_enabled?: boolean | null;
  default_thinking_level?: string | null;
};

export const DEFAULT_MODEL_PROVIDER = 'openai' as const;

export function createDefaultModelProviderFormState(defaults?: ModelProviderFormDefaults) {
  return {
    enabled: true,
    baseUrl: '',
    models: [] as string[],
    modelInput: '',
    apiKey: '',
    thinkingEnabled: defaults?.default_thinking_enabled ?? true,
    thinkingLevel: defaults?.default_thinking_level ?? 'high',
  };
}

export function createDefaultExtensionFormState() {
  return {
    name: '',
    transport: 'http' as const,
    emitMetrics: true,
    logLevelOverride: '' as const,
    httpUrl: '',
    httpTimeoutSeconds: '',
    httpAuthType: 'none' as const,
    httpAuthToken: '',
    httpHeadersJson: '',
    stdioCommand: '',
    stdioArgsText: '',
    stdioEnvJson: '',
    stdioWorkingDirectory: '',
    stdioTimeoutSeconds: '',
  };
}
