import { parseSseStream, type SseEvent } from '../lib/sse';
import { getApiBaseUrl, HttpError } from './http';

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

  const url = `${getApiBaseUrl()}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers,
      signal,
    });
  } catch (err) {
    if (signal?.aborted || (err as { name?: string } | undefined)?.name === 'AbortError') {
      throw new HttpError('请求已取消', 499, { body: err instanceof Error ? err.message : err });
    }
    const baseUrl = getApiBaseUrl();
    const message = baseUrl
      ? `无法连接到后端服务（${baseUrl}）。请确认后端已启动并可访问：${url}，或在 frontend/.env.local 配置 NEXT_PUBLIC_API_BASE_URL。`
      : `无法连接到后端服务。请确认后端已启动（http://127.0.0.1:8000），并在 frontend/.env.local 配置 NEXT_PUBLIC_API_BASE_URL。请求：${url}`;
    throw new HttpError(message, 0, { body: err instanceof Error ? err.message : err });
  }

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

