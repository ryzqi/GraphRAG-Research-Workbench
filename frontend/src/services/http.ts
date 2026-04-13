export class HttpError extends Error {
  status: number;
  requestId?: string;
  body?: unknown;

  constructor(message: string, status: number, opts?: { requestId?: string; body?: unknown }) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.requestId = opts?.requestId;
    this.body = opts?.body;
  }
}

export class ApiConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ApiConfigurationError';
  }
}

export function normalizeApiBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  return trimmed.replace(/\/api\/v1$/, '');
}

function isBrowserRuntime(): boolean {
  return typeof window !== 'undefined';
}

export function resolveApiBaseUrl(
  raw: string | null | undefined,
  options?: { allowSameOrigin?: boolean }
): string {
  const normalizedRaw = raw?.trim();
  if (normalizedRaw) {
    return normalizeApiBaseUrl(normalizedRaw);
  }
  if (options?.allowSameOrigin ?? isBrowserRuntime()) {
    return '';
  }
  throw new ApiConfigurationError(
    'NEXT_PUBLIC_API_BASE_URL 未配置：当前为服务端请求，无法推导后端地址。请显式配置 NEXT_PUBLIC_API_BASE_URL，或改为浏览器同源请求。'
  );
}

function resolveConfiguredApiBaseUrl(): string {
  return resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL, {
    allowSameOrigin: isBrowserRuntime(),
  });
}

function tryResolveConfiguredApiBaseUrl(): string | null {
  try {
    return resolveConfiguredApiBaseUrl();
  } catch (error) {
    if (error instanceof ApiConfigurationError) {
      return null;
    }
    throw error;
  }
}

export function getApiBaseUrl(): string {
  return resolveConfiguredApiBaseUrl();
}

export function getApiOrigin(): string | null {
  const apiBaseUrl = tryResolveConfiguredApiBaseUrl();
  if (!apiBaseUrl) {
    return null;
  }
  try {
    return new URL(apiBaseUrl).origin;
  } catch {
    return null;
  }
}

export function buildApiRequestContext(path: string): {
  baseUrl: string;
  mode: 'explicit' | 'same-origin';
  url: string;
} {
  const baseUrl = resolveConfiguredApiBaseUrl();
  return {
    baseUrl,
    mode: baseUrl ? 'explicit' : 'same-origin',
    url: `${baseUrl}${path}`,
  };
}

export function buildApiRequestUrl(path: string): string {
  return buildApiRequestContext(path).url;
}

function newRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

interface FetchWithTimeoutOptions extends RequestInit {
  requestId?: string;
}

export async function fetchWithTimeout(
  input: string,
  options?: FetchWithTimeoutOptions
): Promise<{ response: Response; requestId: string }> {
  const requestId = options?.requestId ?? newRequestId();
  const { requestId: _ignoredRequestId, ...fetchOptions } = options ?? {};

  try {
    const response = await fetch(input, {
      ...fetchOptions,
    });
    return { response, requestId };
  } catch (err) {
    if ((err as { name?: string } | undefined)?.name === 'AbortError') {
      throw new HttpError('请求已取消', 499, { requestId });
    }
    throw new HttpError('请求失败，无法连接到目标服务', 0, {
      requestId,
      body: err instanceof Error ? err.message : err,
    });
  }
}

export interface ApiFetchOptions extends RequestInit {
  includeRequestIdHeader?: boolean;
}

export function buildBackendConnectivityHint(params: {
  baseUrl: string;
  mode: 'explicit' | 'same-origin';
  url: string;
}): string {
  if (params.mode === 'explicit') {
    return `无法连接到后端服务（${params.baseUrl}）。请确认后端已启动并可访问：${params.url}。`;
  }
  return `无法连接到同源后端服务。请确认当前站点的同源后端路径可访问：${params.url}，或在 frontend/.env.local 配置 NEXT_PUBLIC_API_BASE_URL。`;
}

export async function apiFetch<T>(path: string, init?: ApiFetchOptions): Promise<T> {
  const requestId = newRequestId();
  const headers = new Headers(init?.headers ?? {});
  if (!headers.has('Content-Type') && !(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  // 对可缓存的服务端 GET，允许调用方关闭随机 request id header，
  // 避免 Next/React 按 request init 去重与缓存时被无意义的唯一值打散。
  if (init?.includeRequestIdHeader !== false) {
    headers.set('X-Request-Id', requestId);
  }

  let requestContext: ReturnType<typeof buildApiRequestContext>;
  try {
    requestContext = buildApiRequestContext(path);
  } catch (error) {
    if (error instanceof ApiConfigurationError) {
      throw new HttpError(`${error.message} 请求：${path}`, 500, { requestId });
    }
    throw error;
  }

  let response: Response;
  try {
    const result = await fetchWithTimeout(requestContext.url, {
      ...init,
      headers,
      requestId,
    });
    response = result.response;
  } catch (err) {
    if (err instanceof HttpError) {
      if (err.status === 0 || err.status === 499) {
        const hint = buildBackendConnectivityHint(requestContext);
        throw new HttpError(hint, err.status, { requestId, body: err.body });
      }
      throw err;
    }
    const hint = buildBackendConnectivityHint(requestContext);
    throw new HttpError(hint, 0, { requestId, body: err instanceof Error ? err.message : err });
  }

  const responseRequestId = response.headers.get('x-request-id') ?? undefined;
  const text = await response.text();
  let body: unknown = undefined;
  try {
    body = text ? (JSON.parse(text) as unknown) : undefined;
  } catch {
    body = text;
  }

  if (!response.ok) {
    const message = (body as any)?.error?.message ?? `请求失败（${response.status}）`;
    throw new HttpError(message, response.status, {
      requestId: responseRequestId ?? requestId,
      body,
    });
  }

  return body as T;
}
