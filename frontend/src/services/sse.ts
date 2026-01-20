import { parseSseStream, type SseEvent } from '../lib/sse';
import { buildAuthHeaders, getApiBaseUrl, HttpError } from './http';

export async function openSseStream(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  const headers = new Headers(init.headers ?? {});
  headers.set('Accept', 'text/event-stream');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const authHeaders = buildAuthHeaders();
  for (const [key, value] of Object.entries(authHeaders)) {
    headers.set(key, value);
  }

  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
    signal,
  });

  if (!res.ok) {
    const text = await res.text();
    let body: unknown = undefined;
    try {
      body = text ? (JSON.parse(text) as unknown) : undefined;
    } catch {
      body = text;
    }
    const message = (body as any)?.error?.message ?? `请求失败（${res.status}）`;
    throw new HttpError(message, res.status, { body });
  }

  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('text/event-stream')) {
    throw new Error('服务端未返回 SSE 流');
  }
  if (!res.body) {
    throw new Error('响应没有可读数据流');
  }

  return parseSseStream(res.body);
}
