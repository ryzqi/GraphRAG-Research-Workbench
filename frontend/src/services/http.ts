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
  return trimmed.replace(/\/api\/v1$/, '');
}

const API_BASE_URL = normalizeApiBaseUrl(
  ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000')
);

const AUTH_TOKEN = (import.meta.env.VITE_AUTH_TOKEN as string | undefined)?.trim();
const ADMIN_TOKEN = (import.meta.env.VITE_ADMIN_TOKEN as string | undefined)?.trim();

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function buildAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (AUTH_TOKEN) headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  if (ADMIN_TOKEN) headers['X-Admin-Token'] = ADMIN_TOKEN;
  return headers;
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

  const authHeaders = buildAuthHeaders();
  for (const [key, value] of Object.entries(authHeaders)) {
    headers.set(key, value);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  const responseRequestId = res.headers.get('x-request-id') ?? undefined;
  const text = await res.text();
  const body = text ? (JSON.parse(text) as unknown) : undefined;

  if (!res.ok) {
    const message = (body as any)?.error?.message ?? `请求失败（${res.status}）`;
    throw new HttpError(message, res.status, { requestId: responseRequestId ?? requestId, body });
  }

  return body as T;
}
