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

  // Some environments (IPv6 / system proxy tools) treat "localhost" differently than 127.0.0.1.
  // To avoid "ERR_CONNECTION_REFUSED" where requests never reach the local backend, force localhost -> 127.0.0.1.
  try {
    const url = new URL(normalized);
    if (url.hostname === 'localhost') {
      url.hostname = '127.0.0.1';
      return url.toString().replace(/\/$/, '');
    }
  } catch {
    // Ignore parsing errors (e.g., relative URLs) and fall back to the normalized string.
  }

  return normalized;
}

const API_BASE_URL = (() => {
  const raw = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (!raw) {
    // In dev, prefer same-origin so Vite's dev proxy can forward to the backend.
    // This avoids CORS and also avoids browser/system-proxy loopback edge cases.
    return import.meta.env.DEV ? '' : 'http://127.0.0.1:8000';
  }

  // If the user explicitly configured a backend base URL, honor it.
  // This makes the frontend-backend integration deterministic and avoids relying on Vite's dev proxy.
  return normalizeApiBaseUrl(raw);
})();

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

function newRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const requestId = newRequestId();

  const headers = new Headers(init?.headers ?? {});
  headers.set('Content-Type', 'application/json');
  headers.set('X-Request-Id', requestId);

  const url = `${API_BASE_URL}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers,
    });
  } catch (err) {
    // fetch throws on network errors (e.g., backend not started / connection refused).
    const hint = API_BASE_URL
      ? `无法连接到后端服务（${API_BASE_URL}）。请确认后端已启动并可访问：${url}，或在 frontend/.env.local 配置 VITE_API_BASE_URL。`
      : `无法通过前端代理访问后端。请确认后端已启动（http://127.0.0.1:8000），并检查 frontend/vite.config.ts 的 server.proxy 配置。请求：${url}`;
    throw new HttpError(hint, 0, { requestId, body: err instanceof Error ? err.message : err });
  }

  const responseRequestId = res.headers.get('x-request-id') ?? undefined;
  const text = await res.text();
  let body: unknown = undefined;
  try {
    body = text ? (JSON.parse(text) as unknown) : undefined;
  } catch {
    body = text;
  }

  if (!res.ok) {
    const message = (body as any)?.error?.message ?? `请求失败（${res.status}）`;
    throw new HttpError(message, res.status, { requestId: responseRequestId ?? requestId, body });
  }

  return body as T;
}
