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

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000';

function newRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const requestId = newRequestId();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Request-Id': requestId,
      ...(init?.headers ?? {}),
    },
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
