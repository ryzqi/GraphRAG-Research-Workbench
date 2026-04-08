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

function normalizeApiBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  const normalized = trimmed.replace(/\/api\/v1$/, '');

  try {
    const url = new URL(normalized);
    if (url.hostname === 'localhost') {
      url.hostname = '127.0.0.1';
      return url.toString().replace(/\/$/, '');
    }
  } catch {
    // 相对路径解析失败时直接保留原值。
  }

  return normalized;
}

const API_BASE_URL = (() => {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!raw) {
    // 仅用于本地前后端分离启动时的开发兜底地址。
    return 'http://127.0.0.1:8000';
  }
  return normalizeApiBaseUrl(raw);
})();

const API_ORIGIN = (() => {
  try {
    return new URL(API_BASE_URL).origin;
  } catch {
    return null;
  }
})();

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function getApiOrigin(): string | null {
  return API_ORIGIN;
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

function buildBackendConnectivityHint(url: string): string {
  return `无法连接到后端服务（${API_BASE_URL}）。请确认后端已启动并可访问：${url}，或在 frontend/.env.local 配置 NEXT_PUBLIC_API_BASE_URL。`;
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

  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    const result = await fetchWithTimeout(url, {
      ...init,
      headers,
      requestId,
    });
    response = result.response;
  } catch (err) {
    if (err instanceof HttpError) {
      if (err.status === 0 || err.status === 499) {
        const hint = buildBackendConnectivityHint(url);
        throw new HttpError(hint, err.status, { requestId, body: err.body });
      }
      throw err;
    }
    const hint = buildBackendConnectivityHint(url);
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
    throw new HttpError(message, response.status, { requestId: responseRequestId ?? requestId, body });
  }

  return body as T;
}
